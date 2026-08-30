const BASE = import.meta.env.VITE_API_URL || '/api'

export const apiBase = BASE
const TOKEN_KEY = 'shop_dashboard_token'

const SESSION_KEY = 'shop_dashboard_session'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(SESSION_KEY)
}

/** Роль і імʼя того, хто увійшов.
 *
 * Використовується лише для того, щоб не показувати недоступні розділи.
 * Справжнє обмеження — на бекенді: підміна цього запису в браузері нічого
 * не дає, сервер усе одно поверне 403.
 */
export const setSession = (data) =>
  localStorage.setItem(SESSION_KEY, JSON.stringify({ role: data.role, name: data.name }))

export const getSession = () => {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY)) || { role: 'admin', name: '' }
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

async function request(path, { method = 'GET', body, params } = {}) {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
    })
  }

  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new ApiError('Сесія завершилась', 401)
  }

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

export const api = {
  health: () => request('/health'),


  login: (login, password) => request('/auth/login', { method: 'POST', body: { login, password } }),

  stats: {
    byOperator: (days) => request('/stats/by-operator', { params: { days } }),
    summary: (days = 30) => request('/stats/summary', { params: { days } }),
    series: (days = 30) => request('/stats/series', { params: { days } }),
    topProducts: (days = 30) => request('/stats/top-products', { params: { days } }),
    breakdown: () => request('/stats/status-breakdown'),
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
    remove: (id) => request(`/catalog/products/${id}`, { method: 'DELETE' }),
    purge: (id) => request(`/catalog/products/${id}/purge`, { method: 'DELETE' }),
  },

  orders: {
    list: (params) => request('/orders', { params }),
    get: (id) => request(`/orders/${id}`),
    patch: (id, data) => request(`/orders/${id}`, { method: 'PATCH', body: data }),
    messages: (id, markRead = false) =>
      request(`/orders/${id}/messages`, { params: { mark_read: markRead || undefined } }),
    sendMessage: (id, text) =>
      request(`/orders/${id}/messages`, { method: 'POST', body: { text } }),
    unread: () => request('/orders/unread/counts'),
    // Вкладення тягнеться через бекенд, а не напряму з Telegram:
    // пряме посилання містило б токен бота у відкритому вигляді
    fileUrl: (orderId, messageId) => `${BASE}/orders/${orderId}/files/${messageId}`,
  },

  customers: {
    list: (params) => request('/customers', { params }),
    patch: (id, data) => request(`/customers/${id}`, { method: 'PATCH', body: data }),
    orders: (id) => request(`/customers/${id}/orders`),
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
      const response = await fetch(`${BASE}/backups/${encodeURIComponent(name)}/download`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      })
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
      const response = await fetch(`${BASE}/backups/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body,
      })
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
      const response = await fetch(`${BASE}/backups/${encodeURIComponent(name)}/restore`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body,
      })
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
      const response = await fetch(`${BASE}/media`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body,
      })
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
    download: async (service) => {
      const response = await fetch(`${BASE}/logs/${encodeURIComponent(service)}/download`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      })
      if (!response.ok) throw new Error(`Не вдалося скачати: ${response.status}`)
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `elfar-${service}.log`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 30000)
    },
    read: ({ service, level, event, search, limit, since, until }) => {
      // URLSearchParams, а не склеювання рядків: у пошуку буває будь-що,
      // включно з пробілами та кирилицею, і ручне екранування тут
      // рано чи пізно зламалося б.
      const params = new URLSearchParams({ service, limit: String(limit) })
      if (level) params.set('level', level)
      if (event) params.set('event', event)
      if (search) params.set('search', search)
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
    environment: () => request('/settings/environment'),
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
