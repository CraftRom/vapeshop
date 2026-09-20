import { getInitData } from './telegram'
import { clientLog } from './logger'

const BASE = '/api/shop'
const REQUEST_TIMEOUT_MS = 12000
const GET_RETRIES = 1

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function isTransientStatus(status) {
  return status === 408 || status === 425 || status === 429 || status >= 500
}

async function fetchTimed(url, options) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } finally {
    clearTimeout(timeout)
  }
}

async function responseDetail(res) {
  let detail = `Помилка ${res.status}`
  try {
    const data = await res.clone().json()
    if (typeof data?.detail === 'string') {
      detail = data.detail
    } else if (Array.isArray(data?.detail)) {
      detail = data.detail.map((i) => i.msg).filter(Boolean).join('; ') || detail
    }
  } catch {
    /* тіло не JSON — лишаємо код статусу */
  }
  return detail
}

async function request(path, { method = 'GET', body } = {}) {
  const started = performance.now()
  const logPath = String(path).split('?')[0]
  const maxAttempts = method === 'GET' ? GET_RETRIES + 1 : 1

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    let res
    try {
      res = await fetchTimed(BASE + path, {
        method,
        headers: {
          'Content-Type': 'application/json',
          // Підписаний Telegram рядок — ним бекенд упізнає покупця.
          'X-Telegram-Init-Data': getInitData(),
        },
        body: body ? JSON.stringify(body) : undefined,
      })
    } catch (err) {
      const hidden = document.visibilityState === 'hidden'
      const retry = !hidden && method === 'GET' && attempt < maxAttempts
      if (retry) {
        clientLog('storefront.api.retry', {
          level: 'warning',
          message: err?.name === 'AbortError' ? 'API timeout — повтор GET' : 'Мережева помилка — повтор GET',
          errorName: err?.name || '', method, endpoint: logPath, attempt,
          durationMs: Math.round(performance.now() - started),
        })
        await wait(350 * attempt)
        continue
      }

      // При закритті/згортанні Telegram WebView браузер обриває всі fetch.
      // Це не серверна аварія, тому не засмічуємо журнал шістьма однаковими
      // error-подіями від паралельного refresh().
      if (!hidden) {
        clientLog('storefront.api.network_error', {
          level: 'error',
          message: err?.name === 'AbortError' ? 'API timeout' : (err?.message || 'network error'),
          errorName: err?.name || '', method, endpoint: logPath,
          durationMs: Math.round(performance.now() - started),
        })
      }
      if (err?.name === 'AbortError') {
        const timeoutError = new Error('Сервер не відповідає. Спробуйте ще раз.')
        timeoutError.name = 'TimeoutError'
        throw timeoutError
      }
      throw err
    }

    if (!res.ok) {
      const detail = await responseDetail(res)
      const retry = method === 'GET' && attempt < maxAttempts && isTransientStatus(res.status)
      if (retry) {
        clientLog('storefront.api.retry', {
          level: 'warning', message: `${detail} — повтор GET`, status: res.status,
          method, endpoint: logPath, attempt,
          durationMs: Math.round(performance.now() - started),
        })
        await wait(res.status === 429 ? 900 : 350 * attempt)
        continue
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

  throw new Error('Не вдалося виконати запит')
}

export const api = {
  config: () => request('/config'),
  // Стартові дані одним запитом — замість шести окремих
  bootstrap: () => request('/bootstrap'),
  confirmAge: () => request('/age-confirm', { method: 'POST' }),

  categories: () => request('/categories'),
  productPhoto: async (productId) => {
    const endpoint = `/products/${productId}/photo`
    for (let attempt = 1; attempt <= GET_RETRIES + 1; attempt += 1) {
      let res
      try {
        res = await fetchTimed(`${BASE}${endpoint}`, {
          headers: { 'X-Telegram-Init-Data': getInitData() },
        })
      } catch (err) {
        const hidden = document.visibilityState === 'hidden'
        if (!hidden && attempt <= GET_RETRIES) {
          await wait(350 * attempt)
          continue
        }
        throw err
      }
      if (!res.ok && attempt <= GET_RETRIES && isTransientStatus(res.status)) {
        await wait(res.status === 429 ? 900 : 350 * attempt)
        continue
      }
      if (!res.ok) {
        const error = new Error(`Не вдалося завантажити фото (${res.status})`)
        error.status = res.status
        throw error
      }
      return URL.createObjectURL(await res.blob())
    }
    throw new Error('Не вдалося завантажити фото')
  },
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
  contactPhone: () => request('/contact-phone'),
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

    for (let attempt = 1; attempt <= GET_RETRIES + 1; attempt += 1) {
      let res
      try {
        res = await fetchTimed(`${BASE}${endpoint}`, {
          headers: { 'X-Telegram-Init-Data': getInitData() },
        })
      } catch (err) {
        const hidden = document.visibilityState === 'hidden'
        if (!hidden && attempt <= GET_RETRIES) {
          clientLog('storefront.api.retry', {
            level: 'warning', message: 'Вкладення чату: повтор GET',
            errorName: err?.name || '', method: 'GET', endpoint, attempt,
            durationMs: Math.round(performance.now() - started),
          })
          await wait(350 * attempt)
          continue
        }
        if (!hidden) {
          clientLog('storefront.api.network_error', {
            level: 'error', message: err?.name === 'AbortError' ? 'API timeout' : (err?.message || 'network error'),
            errorName: err?.name || '', method: 'GET', endpoint,
            durationMs: Math.round(performance.now() - started),
          })
        }
        if (err?.name === 'AbortError') {
          const timeoutError = new Error('Сервер не відповідає. Спробуйте ще раз.')
          timeoutError.name = 'TimeoutError'
          throw timeoutError
        }
        throw err
      }

      if (!res.ok && attempt <= GET_RETRIES && isTransientStatus(res.status)) {
        clientLog('storefront.api.retry', {
          level: 'warning', message: `Вкладення чату: HTTP ${res.status} — повтор GET`,
          status: res.status, method: 'GET', endpoint, attempt,
          durationMs: Math.round(performance.now() - started),
        })
        await wait(res.status === 429 ? 900 : 350 * attempt)
        continue
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
    }

    throw new Error('Не вдалося завантажити вкладення')
  },

  chatPhoto: async (orderId, file) => {
    const body = new FormData()
    body.append('file', file)
    const started = performance.now()
    const endpoint = `/orders/${orderId}/chat/photo`
    let res
    try {
      res = await fetchTimed(`${BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'X-Telegram-Init-Data': getInitData() },
        body,
      })
    } catch (err) {
      clientLog('storefront.api.network_error', {
        level: 'error', message: err?.name === 'AbortError' ? 'API timeout' : (err?.message || 'network error'),
        errorName: err?.name || '', method: 'POST', endpoint,
        durationMs: Math.round(performance.now() - started),
      })
      if (err?.name === 'AbortError') {
        const timeoutError = new Error('Фото не завантажилось вчасно. Спробуйте ще раз.')
        timeoutError.name = 'TimeoutError'
        throw timeoutError
      }
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
