import { getInitData } from './telegram'

const BASE = '/api/shop'

async function request(path, { method = 'GET', body } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      // Підписаний Telegram рядок — ним бекенд упізнає покупця
      // Читаємо щоразу: SDK може ініціалізуватись пізніше за модуль
      'X-Telegram-Init-Data': getInitData(),
    },
    body: body ? JSON.stringify(body) : undefined,
  })

  if (!res.ok) {
    let detail = `Помилка ${res.status}`
    try {
      const data = await res.json()
      if (typeof data?.detail === 'string') {
        detail = data.detail
      } else if (Array.isArray(data?.detail)) {
        // Помилки валідації приходять масивом обʼєктів. Без розбору текст
        // перетворився б на «[object Object]» просто в очах покупця.
        detail = data.detail.map((i) => i.msg).filter(Boolean).join('; ') || detail
      }
    } catch {
      /* тіло не JSON — лишаємо код статусу */
    }
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
