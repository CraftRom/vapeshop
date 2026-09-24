const BASE = import.meta.env.VITE_API_URL || '/api'

export const apiBase = BASE
const TOKEN_KEY = 'shop_dashboard_token'

const SESSION_KEY = 'shop_dashboard_session'

export const getToken = () => sessionStorage.getItem(TOKEN_KEY)
export const setToken = (t) => {
  sessionStorage.setItem(TOKEN_KEY, t)
  // При оновленні старої версії прибираємо довгоживучий токен з localStorage.
  localStorage.removeItem(TOKEN_KEY)
}
export const clearToken = () => {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(SESSION_KEY)
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(SESSION_KEY)
}

/** Роль і імʼя того, хто увійшов.
 *
 * Використовується лише для того, щоб не показувати недоступні розділи.
 * Справжнє обмеження — на бекенді: підміна цього запису в браузері нічого
 * не дає, сервер усе одно поверне 403.
 */
export const setSession = (data) => {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify({ role: data.role, name: data.name }))
  localStorage.removeItem(SESSION_KEY)
}

export const getSession = () => {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY)) || { role: 'admin', name: '' }
  } catch {
    return { role: 'admin', name: '' }
  }
}

// Адміністратор магазину або системний: обидва керують каталогом,
// промокодами й обліковими записами.
export const isAdmin = () => ['admin', 'shop_admin'].includes(getSession().role)

// Лише власник .env. Тільки він налаштовує Telegram-групу, бота, Mini App,
// розсилки, тихі години й бекапи — тобто те, помилка в чому кладе не
// окремий відділ роботи, а весь магазин.
export const isSysadmin = () => getSession().role === 'admin'

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

const REQUEST_TIMEOUT_MS = 20000

/** Єдина transport-функція панелі.
 *
 * До цього JSON-запити, вкладення, бекапи й файли мали чотири різні
 * fetch-реалізації: частина не обробляла 401, жодна не мала timeout. При
 * завислому nginx кнопка могла лишитись у стані «Завантаження…» назавжди.
 */
export async function authorizedFetch(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const headers = new Headers(options.headers || {})
  const token = getToken()
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)

  try {
    const response = await fetch(url, { ...options, headers, signal: controller.signal })
    if (response.status === 401) {
      clearToken()
      window.location.href = '/login'
      throw new ApiError('Сесія завершилась', 401)
    }
    return response
  } catch (err) {
    if (err?.name === 'AbortError') {
      throw new ApiError('Сервер не відповідає. Спробуйте ще раз.', 0)
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

export async function consumeOrderEvents(onOrder, signal) {
  const token = getToken()
  if (!token) throw new ApiError('Сесія завершилась', 401)
  const url = new URL(`${BASE}/realtime/orders`, window.location.origin)
  const response = await fetch(url, {
    headers: { Accept: 'text/event-stream', Authorization: `Bearer ${token}` },
    cache: 'no-store',
    signal,
  })
  if (response.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new ApiError('Сесія завершилась', 401)
  }
  if (!response.ok || !response.body) throw new ApiError(`Realtime HTTP ${response.status}`, response.status)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (!signal?.aborted) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const raw = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
      let event = 'message'
      const data = []
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
      }
      if (event !== 'order' || !data.length) continue
      try { onOrder(JSON.parse(data.join('\n'))) } catch { /* malformed live frame: skip */ }
    }
  }
}

async function request(path, { method = 'GET', body, params } = {}) {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
    })
  }

  const response = await authorizedFetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (!response.ok) {
    let detail = ''
    try {
      const data = await response.json()
      if (typeof data.detail === 'string') {
        detail = data.detail
      } else if (Array.isArray(data.detail)) {
        // FastAPI віддає помилки валідації масивом обʼєктів. Без розбору
        // менеджер бачив би «Помилка 422» і не знав, яке поле виправляти.
        detail = data.detail
          .map((item) => {
            const field = (item.loc || []).filter((p) => p !== 'body').join(' → ')
            return field ? `${field}: ${item.msg}` : item.msg
          })
          .filter(Boolean)
          .join('; ')
      }
    } catch { /* тіло не JSON */ }

    if (!detail) {
      // Без цього збій сервера виглядав би як помилка в даних форми.
      if (response.status >= 500) {
        detail = `Сервер відповів помилкою ${response.status}. Перевірте логи: docker compose logs api`
      } else if (response.status === 404) {
        // Найчастіша причина — панель і API розгорнуті окремо, а VITE_API_URL
        // не задано, тож запит пішов на власний домен, де функцій немає.
        detail =
          `API не відповів за адресою ${url.pathname}. ` +
          `Панель звертається до ${BASE}. Якщо бекенд на іншому домені — ` +
          `задайте VITE_API_URL і перезберіть панель.`
      } else {
        detail = `Помилка ${response.status}`
      }
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return null
  return response.json()
}


async function upload(path, formData) {
  const response = await authorizedFetch(
    new URL(`${BASE}${path}`, window.location.origin),
    { method: 'POST', body: formData },
    120000,
  )
  if (!response.ok) { let d; try { d=(await response.json()).detail } catch {} throw new ApiError(typeof d === 'string' ? d : `Помилка ${response.status}`, response.status) }
  return response.json()
}
async function download(path, filename) {
  const response = await authorizedFetch(
    new URL(`${BASE}${path}`, window.location.origin), {}, 120000,
  )
  if (!response.ok) throw new ApiError(`Помилка ${response.status}`, response.status)
  const blob=await response.blob(); const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=filename; a.click(); URL.revokeObjectURL(url)
}

export const api = {
  health: () => request('/health'),


  login: (login, password) => request('/auth/login', { method: 'POST', body: { login, password } }),

  stats: {
    badges: () => request('/stats/badges'),
    // period — календарний ключ, а не «N * 24 годин». Так «Сьогодні»
    // починається опівночі в часовій зоні магазину, а «Цей місяць» — 1 числа.
    byOperator: (period = 'month') => request('/stats/by-operator', { params: { period } }),
    summary: (period = 'month') => request('/stats/summary', { params: { period } }),
    series: (period = 'month') => request('/stats/series', { params: { period } }),
    topProducts: (period = 'month') => request('/stats/top-products', { params: { period } }),
    breakdown: (period = 'month') => request('/stats/status-breakdown', { params: { period } }),
    insights: (period = 'month') => request('/stats/insights', { params: { period } }),
  },

  categories: {
    list: () => request('/catalog/categories'),
    create: (data) => request('/catalog/categories', { method: 'POST', body: data }),
    update: (id, data) => request(`/catalog/categories/${id}`, { method: 'PUT', body: data }),
    remove: (id) => request(`/catalog/categories/${id}`, { method: 'DELETE' }),
    purge: (id) => request(`/catalog/categories/${id}/purge`, { method: 'DELETE' }),
  },

  products: {
    list: (params) => request('/catalog/products', { params }),
    create: (data) => request('/catalog/products', { method: 'POST', body: data }),
    update: (id, data) => request(`/catalog/products/${id}`, { method: 'PUT', body: data }),
    setStock: (id, stock) => request(`/catalog/products/${id}/stock`, { method: 'PATCH', body: { stock } }),
    adjustStock: (id, delta) => request(`/catalog/products/${id}/stock-delta`, { method: 'PATCH', body: { delta } }),
    remove: (id) => request(`/catalog/products/${id}`, { method: 'DELETE' }),
    purge: (id) => request(`/catalog/products/${id}/purge`, { method: 'DELETE' }),
    importXlsx: (form) => upload('/catalog/product-transfer/import', form),
    exportXlsx: () => download('/catalog/product-transfer/export', 'elfar-products.xlsx'),
  },

  orders: {
    list: (params) => request('/orders', { params }),
    get: (id) => request(`/orders/${id}`),
    patch: (id, data) => request(`/orders/${id}`, { method: 'PATCH', body: data }),
    messages: (id, markRead = false, afterId = null, beforeId = null, limit = null) =>
      request(`/orders/${id}/messages`, {
        params: {
          mark_read: markRead || undefined,
          after_id: afterId === null || afterId === undefined ? undefined : afterId,
          before_id: beforeId === null || beforeId === undefined ? undefined : beforeId,
          limit: limit || undefined,
        },
      }),
    markMessagesRead: (id) => request(`/orders/${id}/messages/read`, { method: 'POST' }),
    sendMessage: (id, text) =>
      request(`/orders/${id}/messages`, { method: 'POST', body: { text } }),
    unread: () => request('/orders/unread/counts'),
    // Накладна й CRM — ті самі поля замовлення, звідки б не прийшла зміна
    waybillReadiness: (id) => request(`/orders/${id}/waybill/readiness`),
    createWaybill: (id) => request(`/orders/${id}/waybill`, { method: 'POST' }),
    deleteWaybill: (id) => request(`/orders/${id}/waybill`, { method: 'DELETE' }),
    // PDF тягне сервер: адреса кабінету Нової пошти містить ключ API
    waybillLabelUrl: (id) => `${BASE}/orders/${id}/waybill/label`,
    crmSync: (id) => request(`/orders/${id}/crm-sync`, { method: 'POST' }),
    // Робочий довідник доступний всім staff і читається напряму з CRM.
    salesdriveStatuses: () => request('/orders/salesdrive-statuses'),
    // Назву статусу браузер не надсилає: backend сам звіряє ID з SalesDrive.
    salesdriveStatus: (id, statusId) => request(`/orders/${id}/salesdrive-status`, { method: 'PATCH', body: { status_id: String(statusId) } }),
    salesdriveUpdate: (id, body) => request(`/orders/${id}/salesdrive`, { method: 'PATCH', body }),
    salesdriveRefresh: (id, force = false) => request(`/orders/${id}/salesdrive-refresh`, { method: 'POST', params: { force: force || undefined } }),
    // Вкладення тягнеться через бекенд, а не напряму з Telegram:
    // пряме посилання містило б токен бота у відкритому вигляді
    fileUrl: (orderId, messageId) => `${BASE}/orders/${orderId}/files/${messageId}`,
  },

  notifications: {
    list: (limit = 60) => request('/notifications', { params: { limit } }),
    poll: (afterId, limit = 60) => request('/notifications/poll', {
      params: { after_id: afterId === null || afterId === undefined ? undefined : afterId, limit },
    }),
    read: (id) => request(`/notifications/${id}/read`, { method: 'POST' }),
    readAll: () => request('/notifications/read-all', { method: 'POST' }),
  },

  support: {
    list: (status = 'open') => request('/support', { params: { status } }),
    stats: () => request('/support/stats'),
    get: (id) => request(`/support/${id}`),
    messages: (id, markRead = false) =>
      request(`/support/${id}/messages`, { params: { mark_read: markRead || undefined } }),
    send: (id, text) =>
      request(`/support/${id}/messages`, { method: 'POST', body: { text } }),
    setStatus: (id, status) =>
      request(`/support/${id}`, { method: 'PATCH', body: { status } }),
    remove: (id) => request(`/support/${id}`, { method: 'DELETE' }),
    unread: () => request('/support/unread/count'),
    fileUrl: (threadId, messageId) => `${BASE}/support/${threadId}/files/${messageId}`,
  },

  customers: {
    list: (params) => request('/customers', { params }),
    patch: (id, data) => request(`/customers/${id}`, { method: 'PATCH', body: data }),
    orders: (id) => request(`/customers/${id}/orders`),
    wishlists: (id) => request(`/customers/${id}/wishlists`),
  },

  promos: {
    list: () => request('/promos'),
    create: (data) => request('/promos', { method: 'POST', body: data }),
    update: (id, data) => request(`/promos/${id}`, { method: 'PUT', body: data }),
    remove: (id) => request(`/promos/${id}`, { method: 'DELETE' }),
    purge: (id) => request(`/promos/${id}/purge`, { method: 'DELETE' }),
  },

  ordersAdmin: {
    remove: (id) => request(`/orders/${id}`, { method: 'DELETE' }),
    purge: () => request('/orders?confirm=DELETE%20ALL', { method: 'DELETE' }),
  },

  backups: {
    list: () => request('/backups'),
    create: () => request('/backups/create', { method: 'POST' }),
    remove: (name) => request(`/backups/${encodeURIComponent(name)}`, { method: 'DELETE' }),

    // Скачування йде через fetch, а не звичайним посиланням: файл віддається
    // лише з токеном, а тег <a> заголовків не надсилає. Тому забираємо
    // тіло в blob і віддаємо його браузеру вже локальним посиланням.
    download: async (name) => {
      const response = await authorizedFetch(
        `${BASE}/backups/${encodeURIComponent(name)}/download`, {}, 120000,
      )
      if (!response.ok) throw new Error(`Не вдалося скачати: ${response.status}`)
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = name
      link.click()
      // Звільняємо памʼять: blob живе, доки на нього є посилання, а дамп
      // може важити сотні мегабайтів.
      setTimeout(() => URL.revokeObjectURL(url), 30000)
    },

    upload: async (file) => {
      const body = new FormData()
      body.append('file', file)
      const response = await authorizedFetch(
        `${BASE}/backups/upload`, { method: 'POST', body }, 120000,
      )
      if (!response.ok) {
        let message = `Помилка ${response.status}`
        try { message = (await response.json()).detail || message } catch { /* не JSON */ }
        throw new Error(message)
      }
      return response.json()
    },

    restore: async (name, confirm) => {
      const body = new FormData()
      body.append('confirm', confirm)
      const response = await authorizedFetch(
        `${BASE}/backups/${encodeURIComponent(name)}/restore`, { method: 'POST', body }, 120000,
      )
      if (!response.ok) {
        let message = `Помилка ${response.status}`
        try { message = (await response.json()).detail || message } catch { /* не JSON */ }
        throw new Error(message)
      }
      return response.json()
    },
  },

  media: {
    list: () => request('/media'),
    remove: (name) => request(`/media/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    upload: async (file) => {
      // FormData, а не JSON: файл треба слати як є. Заголовок Content-Type
      // тут не ставимо навмисно — браузер додасть його разом із boundary,
      // без якого сервер не розбере тіло запиту.
      const body = new FormData()
      body.append('file', file)
      const response = await authorizedFetch(
        `${BASE}/media`, { method: 'POST', body }, 120000,
      )
      if (!response.ok) {
        let message = `Помилка ${response.status}`
        try {
          const data = await response.json()
          message = data.detail || message
        } catch {
          // Тіло не JSON — лишаємо код відповіді, він теж щось каже
        }
        throw new Error(message)
      }
      return response.json()
    },
  },

  logs: {
    services: () => request('/logs/services'),
    events: (service) => request(`/logs/events?service=${encodeURIComponent(service)}`),

    // Через fetch із токеном: файл віддається лише системному
    // адміністраторові, а тег <a> заголовків не надсилає.
    //
    // Фільтри передаємо ті самі, що й на екран: файл має містити рівно
    // те, що людина бачить, і стільки записів, скільки вона вибрала.
    // Раніше сюди не йшло нічого, і «скачати» завжди віддавало весь файл.
    download: async ({
      service, level, event, search, severity, limit, since, until, full,
    }) => {
      const params = new URLSearchParams()
      if (full) {
        params.set('full', '1')
      } else {
        params.set('limit', String(limit))
        if (level) params.set('level', level)
        if (event) params.set('event', event)
        if (search) params.set('search', search)
        if (severity) params.set('severity', severity)
        if (since) params.set('since', since)
        if (until) params.set('until', until)
      }
      const response = await authorizedFetch(
        `${BASE}/logs/${encodeURIComponent(service)}/download?${params}`, {}, 120000,
      )
      if (!response.ok) throw new Error(`Не вдалося скачати: ${response.status}`)
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `elfar-${service}${full ? '-full' : ''}.log`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 30000)
    },
    read: ({ service, level, event, search, severity, limit, since, until }) => {
      // URLSearchParams, а не склеювання рядків: у пошуку буває будь-що,
      // включно з пробілами та кирилицею, і ручне екранування тут
      // рано чи пізно зламалося б.
      const params = new URLSearchParams({ service, limit: String(limit) })
      if (level) params.set('level', level)
      if (event) params.set('event', event)
      if (search) params.set('search', search)
      if (severity) params.set('severity', severity)
      if (since) params.set('since', since)
      if (until) params.set('until', until)
      return request(`/logs?${params.toString()}`)
    },
  },

  operators: {
    list: () => request('/operators'),
    create: (data) => request('/operators', { method: 'POST', body: data }),
    update: (id, data) => request(`/operators/${id}`, { method: 'PUT', body: data }),
    remove: (id) => request(`/operators/${id}`, { method: 'DELETE' }),
    purge: (id) => request(`/operators/${id}/purge`, { method: 'DELETE' }),
  },

  settings: {
    environment: () => request('/settings/environment'),
    salesdriveCheck: () => request('/integrations/salesdrive/check', { method: 'POST' }),
    salesdriveDictionaries: () => request('/integrations/salesdrive/dictionaries'),
    get: () => request('/settings'),
    update: (data) => request('/settings', { method: 'PUT', body: data }),
  },

  broadcasts: {
    list: () => request('/broadcasts'),
    segments: () => request('/broadcasts/segments'),
    preview: (segment) => request('/broadcasts/preview', { method: 'POST', body: segment }),
    create: (data) => request('/broadcasts', { method: 'POST', body: data }),
    send: (id) => request(`/broadcasts/${id}/send`, { method: 'POST' }),
    schedule: (id, scheduledAt) =>
      request(`/broadcasts/${id}/schedule`, {
        method: 'POST',
        body: { scheduled_at: scheduledAt },
      }),
    unschedule: (id) => request(`/broadcasts/${id}/unschedule`, { method: 'POST' }),
    remove: (id) => request(`/broadcasts/${id}`, { method: 'DELETE' }),
  },
}
