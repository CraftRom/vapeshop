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

const PAGES = ['/', '/orders', '/orders/41', '/catalog', '/customers', '/support', '/promos', '/broadcasts', '/landing-pages', '/logs', '/settings', '/operators', '/backups', '/instructions']
const WIDTHS = [320, 768, 1280]
const INTERACTIVE = new Set(['button', 'link', 'textbox', 'searchbox', 'combobox', 'checkbox', 'switch', 'radio', 'spinbutton', 'slider', 'tab', 'menuitem'])

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
      const h1 = await page.locator('h1:visible').count()
      check(h1 === 1, `${label}: exactly one visible h1 (found ${h1})`)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      check(overflow <= 0, `${label}: no page-wide horizontal scroll (${overflow}px)`)
      const { nodes } = await cdp.send('Accessibility.getFullAXTree')
      const unnamed = nodes.filter((node) => !node.ignored && INTERACTIVE.has(node.role?.value) && !String(node.name?.value || '').trim())
      const described = []
      for (const node of unnamed.slice(0, 8)) {
        if (!node.backendDOMNodeId) { described.push(node.role.value); continue }
        const { object } = await cdp.send('DOM.resolveNode', { backendNodeId: node.backendDOMNodeId })
        const { result } = await cdp.send('Runtime.callFunctionOn', { objectId: object.objectId, returnByValue: true, functionDeclaration: 'function(){const r=this.getBoundingClientRect();return r.width&&r.height?this.outerHTML.slice(0,140):""}' })
        if (result.value) described.push(`${node.role.value} ${result.value}`)
      }
      check(described.length === 0, `${label}: every visible control has an accessible name ${described.join(' | ')}`)
      const duplicates = await page.evaluate(() => { const seen = {}; for (const el of document.querySelectorAll('[id]')) seen[el.id] = (seen[el.id] || 0) + 1; return Object.keys(seen).filter((id) => seen[id] > 1) })
      check(duplicates.length === 0, `${label}: ids are unique ${duplicates.join(', ')}`)
      const small = await page.evaluate(() => [...document.querySelectorAll('button, select, input:not([type=checkbox]):not([type=radio]):not([type=hidden]), [role=button]')]
        .filter((el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && (r.width < 24 || r.height < 24) && !el.closest('.sr-only') })
        .map((el) => `${el.tagName.toLowerCase()}.${el.className || ''} ${Math.round(el.getBoundingClientRect().width)}×${Math.round(el.getBoundingClientRect().height)} «${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 30)}»`))
      check(small.length === 0, `${label}: controls are at least 24×24 px ${small.slice(0, 6).join(' | ')}`)
      check(errors.length === 0, `${label}: no runtime errors ${errors.join('; ')}`)
      if (width === 320) await page.screenshot({ path: `${output}/a11y-${path.replace(/\W+/g, '-') || 'home'}-${width}.png` })
    }
    await page.close()
  }
} finally { await browser.close() }
console.log(`A11Y MATRIX: ${checks - failures.length}/${checks}`)
if (failures.length) process.exitCode = 1
