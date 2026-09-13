import { getInitData } from './telegram'
import { clientLog } from './logger'

const BASE = '/api/shop'

async function request(path, { method = 'GET', body } = {}) {
  const started = performance.now()
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 12000)
  const logPath = String(path).split('?')[0]
  let res
  try {
    res = await fetch(BASE + path, {
      method,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        // Підписаний Telegram рядок — ним бекенд упізнає покупця.
        'X-Telegram-Init-Data': getInitData(),
      },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch (err) {
    clientLog('storefront.api.network_error', {
      level: 'error',
      message: err?.name === 'AbortError' ? 'API timeout' : (err?.message || 'network error'),
      errorName: err?.name || '',
      method, endpoint: logPath,
      durationMs: Math.round(performance.now() - started),
    })
    throw err
  } finally {
    clearTimeout(timeout)
  }

  if (!res.ok) {
    let detail = `Помилка ${res.status}`
    try {
      const data = await res.json()
      if (typeof data?.detail === 'string') {
        detail = data.detail
      } else if (Array.isArray(data?.detail)) {
        detail = data.detail.map((i) => i.msg).filter(Boolean).join('; ') || detail
      }
    } catch {
      /* тіло не JSON — лишаємо код статусу */
    }
    clientLog('storefront.api.http_error', {
      level: res.status >= 500 ? 'error' : 'warning',
      message: detail,
      status: res.status,
      method, endpoint: logPath,
      durationMs: Math.round(performance.now() - started),
    })
    const error = new Error(detail)
    error.status = res.status
    throw error
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  config: () => request('/config'),
  // Стартові дані одним запитом — замість шести окремих
  bootstrap: () => request('/bootstrap'),
  confirmAge: () => request('/age-confirm', { method: 'POST' }),

  categories: () => request('/categories'),
  products: ({ categoryId, search } = {}) => {
    const q = new URLSearchParams()
    if (categoryId) q.set('category_id', categoryId)
    if (search) q.set('search', search)
    const qs = q.toString()
    return request(`/products${qs ? `?${qs}` : ''}`)
  },

  cart: () => request('/cart'),
  changeCart: (productId, delta) =>
    request('/cart', { method: 'POST', body: { product_id: productId, delta } }),
  clearCart: () => request('/cart', { method: 'DELETE' }),

  checkPromo: (code) => request('/promo/check', { method: 'POST', body: { code } }),
  profile: () => request('/profile'),
  orders: () => request('/orders'),
  checkout: (data) => request('/checkout', { method: 'POST', body: data }),

  // Довідник Нової пошти. Ходимо через свій бекенд, а не напряму до
  // перевізника: ключ приватний, а політика безпеки вітрини й так
  // дозволяє запити лише на власний домен.
  // Вкладення йде окремим шляхом: multipart, а не JSON, тож спільний
  // request() з його заголовками тут не підходить.
  // Вкладення тягнемо як двійкові дані, а не посилання в src: до запиту
  // треба додати підпис Telegram, а тег <img> заголовків не надсилає.
  chatFile: async (orderId, messageId) => {
    const started = performance.now()
    const endpoint = `/orders/${orderId}/chat/${messageId}/file`
    let res
    try {
      res = await fetch(
        `${BASE}${endpoint}`,
        { headers: { 'X-Telegram-Init-Data': getInitData() } },
      )
    } catch (err) {
      clientLog('storefront.api.network_error', {
        level: 'error', message: err?.message || 'network error',
        errorName: err?.name || '', method: 'GET', endpoint,
        durationMs: Math.round(performance.now() - started),
      })
      throw err
    }
    if (!res.ok) {
      clientLog('storefront.api.http_error', {
        level: res.status >= 500 ? 'error' : 'warning',
        message: `Вкладення чату: HTTP ${res.status}`,
        status: res.status, method: 'GET', endpoint,
        durationMs: Math.round(performance.now() - started),
      })
      const error = new Error(
        res.status === 410
          ? 'Вкладення видалене за строком зберігання'
          : 'Не вдалося завантажити вкладення',
      )
      error.status = res.status
      throw error
    }
    return URL.createObjectURL(await res.blob())
  },

  chatPhoto: async (orderId, file) => {
    const body = new FormData()
    body.append('file', file)
    const started = performance.now()
    const endpoint = `/orders/${orderId}/chat/photo`
    let res
    try {
      res = await fetch(`${BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'X-Telegram-Init-Data': getInitData() },
        body,
      })
    } catch (err) {
      clientLog('storefront.api.network_error', {
        level: 'error', message: err?.message || 'network error',
        errorName: err?.name || '', method: 'POST', endpoint,
        durationMs: Math.round(performance.now() - started),
      })
      throw err
    }
    if (!res.ok) {
      let detail = `Помилка ${res.status}`
      try {
        detail = (await res.json()).detail || detail
      } catch {
        /* тіло не JSON — лишаємо код статусу */
      }
      clientLog('storefront.api.http_error', {
        level: res.status >= 500 ? 'error' : 'warning',
        message: detail, status: res.status, method: 'POST', endpoint,
        durationMs: Math.round(performance.now() - started),
      })
      const error = new Error(detail)
      error.status = res.status
      throw error
    }
    return res.json()
  },

  cancelOrder: (id) => request(`/orders/${id}/cancel`, { method: 'POST' }),

  delivery: {
    cities: (q) => request(`/delivery/cities?q=${encodeURIComponent(q)}`),
    price: (cityRef, settlementRef, method, paymentMethod) =>
      request(
        `/delivery/price?city_ref=${encodeURIComponent(cityRef || '')}` +
        `&settlement_ref=${encodeURIComponent(settlementRef || '')}` +
        `&method=${encodeURIComponent(method)}` +
        `&payment_method=${encodeURIComponent(paymentMethod)}`,
      ),
    warehouses: (cityRef, settlementRef, q = '') =>
      request(
        `/delivery/warehouses?city_ref=${encodeURIComponent(cityRef || '')}` +
        `&settlement_ref=${encodeURIComponent(settlementRef || '')}` +
        `&q=${encodeURIComponent(q)}`,
      ),
  },

  wishlists: {
    list: () => request('/wishlists'),
    create: (name) => request('/wishlists', { method: 'POST', body: { name } }),
    rename: (id, name) => request(`/wishlists/${id}`, { method: 'PUT', body: { name } }),
    remove: (id) => request(`/wishlists/${id}`, { method: 'DELETE' }),
    // Один ендпоінт і додає, і прибирає — стан кнопки завжди відповідає серверу
    toggle: (id, productId) =>
      request(`/wishlists/${id}/items`, { method: 'POST', body: { product_id: productId } }),
  },

  chat: {
    list: (orderId) => request(`/orders/${orderId}/chat`),
    send: (orderId, text) =>
      request(`/orders/${orderId}/chat`, { method: 'POST', body: { text } }),
  },
}
