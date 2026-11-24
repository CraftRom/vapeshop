// UI-014 / UI-026: every key dashboard page at phone, tablet and desktop
// widths. Checks what can be checked mechanically and is never acceptable:
//   • one visible h1;
//   • no page-wide horizontal scroll (tables scroll inside their own box);
//   • every interactive element has an accessible name — taken from
//     Chromium's own accessibility tree, not guessed from the DOM;
//   • no duplicate ids (they break label/aria references);
//   • buttons and form controls are at least 24×24 CSS px (WCAG 2.2, 2.5.8);
//   • no runtime errors.
// Keyboard paths, screen-reader wording and visual review stay manual.
import { chromium } from 'playwright'
import { auditPage } from './a11y-audit.mjs'
import { readFileSync, mkdirSync } from 'node:fs'

const BASE = process.env.DASHBOARD_URL || 'http://127.0.0.1:5173'
const output = process.env.QA_OUTPUT_DIR || 'qa/output'
mkdirSync(output, { recursive: true })
const analytics = JSON.parse(readFileSync(new URL('./analytics-fixture.json', import.meta.url)))
const settings = JSON.parse(readFileSync(new URL('./settings-fixture.json', import.meta.url)))

const order = (id) => ({
  id, status: 'new', total: '1249.50', subtotal: '1249.50', discount: '0', bonus_used: '0', payment_method: 'card',
  items: [{ id: 1, product_id: 3, name: 'Рідина для POD-систем з дуже довгою назвою для перевірки переносу', price: '1249.50', qty: 1 }],
  contact_name: 'Олена Коваль', contact_phone: '+380671234567', delivery_method: 'warehouse', delivery_city: 'Київ',
  delivery_address: 'Відділення 12', created_at: '2026-11-14T08:00:00Z', can_chat: true, user: { id: 5, tg_id: 123 },
  attribution: { source: 'telegram_bot' }, business_state: 'pending',
})
const product = (id) => ({ id, sku: `SKU-${id}`, name: `Товар ${id}`, brand: 'Бренд', price: '450', stock: id % 3, is_active: true, has_photo: id % 2 === 0, category_id: 1, variants: [] })

function data(path) {
  if (path.endsWith('/auth/session')) return { role: 'admin', name: 'QA', csrf_token: 'qa', operator_id: 1, editable_settings: Object.keys(settings) }
  if (path === '/api/settings') return settings
  if (path.endsWith('/stats/report')) return structuredClone(analytics)
  if (path.endsWith('/stats/months')) return { months: [], timezone: 'Europe/Kyiv' }
  if (path.endsWith('/stats/order-sources')) return { total: 0, items: [] }
  if (path.endsWith('/stats/spend')) return []
  if (path.endsWith('/orders/operations')) return { generated_at: '2026-11-18T08:00:00Z', orders: { new: 2, open: 3, without_tracking: 1 }, channels: { bot: 2, miniapp: 1, unknown: 0 }, stock: { available: 10, low: 1, out: 2, unpriced: 0, missing_photos: 1 }, low_stock_threshold: 3, queue: [{ ...order(41), name: 'Олена Коваль', phone: '+380671234567' }], products: [product(2)] }
  if (path === '/api/orders') return { items: [order(41), order(40)], total: 2, limit: 50, offset: 0, has_more: false }
  if (/\/api\/orders\/\d+$/.test(path)) return order(Number(path.split('/').pop()))
  if (path.includes('salesdrive-statuses')) return { statuses: [{ id: 1, name: 'Новий' }, { id: 2, name: 'Відправлено' }] }
  if (path.includes('/messages')) return []
  if (path.endsWith('/catalog/products')) return { items: [product(1), product(2), product(3)], total: 3, limit: 20, offset: 0 }
  if (path.endsWith('/catalog/categories')) return [{ id: 1, name: 'Рідини', is_active: true, products_count: 3 }]
  if (path.endsWith('/catalog/subcategories')) return []
  if (path === '/api/customers/5') return { id: 5, first_name: 'Олена', username: 'olena', tg_id: 123, phone: '+380671234567', referral_code: 'OLENA1', orders_count: 3, total_spent: '3200', bonus_balance: '45', created_at: '2026-01-02T00:00:00Z', is_blocked: false }
  if (path === '/api/customers/5/summary') return { user_ids: [5], telegram_connected: true,
    stats: { orders: 3, sales: 2, lost: 1, revenue: '3200.00', average_check: '1600.00', ordered_sum: '3200.00', average_order: '1600.00', first_order_at: '2026-05-01T00:00:00Z', last_order_at: '2026-11-10T00:00:00Z', bonus_balance: '45.00' },
    channels: [{ key: 'bot', label: 'Бот', orders: 2 }, { key: 'miniapp', label: 'Mini App', orders: 1 }], categories: [{ name: 'Рідини', qty: 3, amount: '2400.00' }], products: [{ name: 'Рідина 30 мл', qty: 3 }],
    order_chats: [{ order_id: 41, messages: 2, unread: 1, last_message_at: '2026-11-10T10:00:00Z' }], support_threads: [{ id: 7, status: 'open', created_at: '2026-11-01T00:00:00Z', last_message_at: '2026-11-02T00:00:00Z', closed_at: null }] }
  if (/\/api\/customers\/5\/orders$/.test(path)) return { items: [order(41)], total: 1, limit: 20, offset: 0, has_more: false }
  if (path === '/api/customers/5/wishlists') return []
  if (path === '/api/customers') return { items: [{ id: 5, first_name: 'Олена', username: 'olena', tg_id: 123, phone: '+380671234567', referral_code: 'OLENA1', orders_count: 3, total_spent: '3200', bonus_balance: '45', created_at: '2026-01-02T00:00:00Z', is_blocked: false }], total: 1 }
  if (path === '/api/operators') return [{ id: 1, login: 'qa', name: 'QA', role: 'admin', created_at: '2026-01-01T00:00:00Z' }, { id: 2, login: 'manager', name: 'Менеджер', role: 'operator', created_at: '2026-01-01T00:00:00Z' }]
  if (path === '/api/backups') return { items: [], total: 0, totalBytes: 0, freeBytes: 10 ** 9, retentionDays: 14, restoreMode: 'server' }
  if (path === '/api/support') return []
  if (path === '/api/support/stats') return { open: 0, closed: 0, total: 0, clients: 0, unread: 0 }
  if (path === '/api/promos') return []
  if (path === '/api/broadcasts') return []
  if (path === '/api/landing-pages') return []
  if (path === '/api/broadcasts/segments') return [{ type: 'all', label: 'Усі клієнти' }]
  if (path === '/api/logs/services') return { services: ['api'], logDir: '/data/logs', usage: { totalBytes: 1000, budgetBytes: 10 ** 8, maxBytesPerFile: 10 ** 7, backupCount: 5 } }
  if (path === '/api/logs/events') return { events: [] }
  if (path === '/api/logs') return { records: [], returned: 0, scanned: 0, truncated: false, diagnostics: null }
  if (path.includes('notifications')) return { items: [], unread: 0 }
  if (path.includes('badges')) return { orders_new: 0, support_unread: 0 }
  if (path.includes('dictionaries')) return { statuses: [], payments: [], deliveries: [] }
  if (path.includes('environment')) return { items: [] }
  return {}
}

const PAGES = ['/', '/orders', '/orders/41', '/catalog', '/customers', '/customers/5', '/support', '/promos', '/broadcasts', '/landing-pages', '/logs', '/settings', '/operators', '/backups', '/instructions']
const WIDTHS = [320, 768, 1280]

const browser = await chromium.launch()
const failures = []
let checks = 0
const check = (ok, label) => { checks++; console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`); if (!ok) failures.push(label) }
try {
  for (const width of WIDTHS) {
    const page = await browser.newPage({ viewport: { width, height: 900 } })
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.route('**/api/**', (route) => route.fulfill({ json: data(new URL(route.request().url()).pathname) }))
    const cdp = await page.context().newCDPSession(page)
    for (const path of PAGES) {
      const label = `${width}px ${path}`
      errors.length = 0
      await page.goto(BASE + path)
      await page.locator('h1').first().waitFor()
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(150)
      await auditPage(page, cdp, label, check, { errors })
      if (path === '/customers' && width === 1280) {
        check(await page.getByRole('link', { name: 'Олена' }).first().getAttribute('href') === '/customers/5', 'customer name links to the customer card')
      }
      if (path === '/customers/5') {
        check(await page.locator('h1').first().innerText() === 'Олена', `${label}: Telegram name is the card title`)
        const stats = await page.getByRole('region', { name: 'Статистика покупок' }).innerText()
        check(/середній чек\s+1\s600,00/i.test(stats) && /сума покупок\s+3\s200,00/i.test(stats), `${label}: revenue and average check`)
        check(await page.getByRole('link', { name: 'Чат замовлення #41' }).getAttribute('href') === '/orders/41', `${label}: order chat opens the order`)
        check(await page.getByRole('link', { name: 'Звернення в підтримку #7' }).getAttribute('href') === '/support?thread=7', `${label}: support thread link`)
        check(await page.getByText('Рідини').first().isVisible(), `${label}: favourite category`)
      }
      if (width === 320) await page.screenshot({ path: `${output}/a11y-${path.replace(/\W+/g, '-') || 'home'}-${width}.png` })
    }
    await page.close()
  }
} finally { await browser.close() }
console.log(`A11Y MATRIX: ${checks - failures.length}/${checks}`)
if (failures.length) process.exitCode = 1
