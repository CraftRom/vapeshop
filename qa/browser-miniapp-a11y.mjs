// Mini App storefront: the same mechanical accessibility and layout checks as
// the dashboard matrix, on the screens a buyer walks through, at phone and
// tablet widths in both Telegram colour schemes.
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { pageFixture } from './paged-fixture.mjs'
import { auditPage, auditAxe } from './a11y-audit.mjs'

const BASE = (process.env.MINIAPP_URL || 'http://127.0.0.1:5174') + '/app/'
const output = process.env.QA_OUTPUT_DIR || 'qa/output'
mkdirSync(output, { recursive: true })

const goods = [
  { id: 1, name: 'Рідина для POD-систем з дуже довгою назвою для вузького екрана', price: '1249', old_price: '1490', is_sale: true, is_new: true, stock: 3, description: 'Опис товару. '.repeat(20) },
  { id: 2, name: 'Крем для рук', price: '320', stock: 0 },
  ...Array.from({ length: 6 }, (_, i) => ({ id: i + 3, name: `Товар ${i + 3}`, price: String(200 + i * 30), stock: 5 })),
]

function data(path, method, body, state) {
  if (path.endsWith('/config')) return { age_confirmed: true, min_age: 18, shop_name: 'ELFAR', currency: 'грн', bonus_enabled: true, referral_enabled: true, delivery_methods: ['Нова пошта'], payment_methods: ['На рахунок'] }
  if (path.endsWith('/cart')) {
    if (method === 'POST' && body?.product_id === 1) state.qty = Math.max(0, Math.min(3, state.qty + body.delta))
    return { lines: state.qty ? [{ product_id: 1, name: goods[0].name, qty: state.qty, stock: 3, price: '1249', line_total: String(state.qty * 1249) }] : [], subtotal: String(state.qty * 1249) }
  }
  if (path.endsWith('/orders') || path.endsWith('/orders/active') || path.endsWith('/orders/chattable')) return [{ id: 41, status: 'new', can_chat: true, chat_until: null, total: '1249', items: [{ name: goods[0].name, qty: 1, price: '1249' }], created_at: '2026-11-14T08:00:00Z' }]
  if (path.endsWith('/chat/access')) return { can_chat: true, chat_until: null, completed_at: null }
  if (path.endsWith('/chat')) return [{ id: 1, text: 'Вітаємо! Чим допомогти?', direction: 'out', created_at: '2026-11-14T08:05:00Z' }]
  if (path.endsWith('/profile')) return { first_name: 'Олена', bonus_balance: '45', orders_count: 1, referral_code: 'OLENA1' }
  if (path.endsWith('/categories')) return [{ id: 1, name: 'Рідини', products_count: 6 }, { id: 2, name: 'Картриджі', products_count: 2 }]
  if (/\/products\/\d+$/.test(path)) return goods.find((item) => item.id === Number(path.split('/').pop()))
  if (path.endsWith('/products')) return goods
  if (path.endsWith('/wishlists')) return [{ id: 1, name: 'Відкладене', product_ids: [], size: 0 }]
  return []
}

const browser = await chromium.launch()
const failures = []
let checks = 0
const check = (ok, label) => { checks++; console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`); if (!ok) failures.push(label) }
try {
  for (const { width, scheme } of [{ width: 320, scheme: 'dark' }, { width: 390, scheme: 'light' }, { width: 768, scheme: 'dark' }]) {
    const page = await browser.newPage({ viewport: { width, height: 800 } })
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    const state = { qty: 0 }
    await page.addInitScript((colorScheme) => {
      window.Telegram = { WebApp: { initData: 'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test', platform: 'tdesktop', colorScheme, initDataUnsafe: { user: { id: 123 } }, ready() {}, expand() {}, disableVerticalSwipes() {}, onEvent() {}, offEvent() {} } }
    }, scheme)
    await page.route('https://telegram.org/**', (route) => route.fulfill({ body: '' }))
    await page.route('**/api/**', async (route) => {
      const request = route.request()
      let body = null
      try { body = request.postDataJSON() } catch { body = null }
      await route.fulfill({ json: pageFixture(route, data(new URL(request.url()).pathname, request.method(), body, state)) })
    })
    const cdp = await page.context().newCDPSession(page)
    const nav = page.getByRole('navigation', { name: 'Розділи магазину' })
    const audit = async (screen) => {
      await page.waitForTimeout(250)
      await auditPage(page, cdp, `${width}px ${scheme} ${screen}`, check, { errors })
      await auditAxe(page, `${width}px ${scheme} ${screen}`, check)
      errors.length = 0
      if (width === 320) await page.screenshot({ path: `${output}/miniapp-a11y-${screen}-${width}.png` })
    }

    await page.goto(BASE)
    await page.locator('.store-card').first().waitFor()
    await audit('catalog')

    await page.locator('.store-card-title').first().click()
    await page.getByRole('heading', { name: goods[0].name, exact: true }).waitFor()
    await audit('product')
    await page.getByRole('button', { name: 'Назад до каталогу' }).click()
    await page.locator('.store-card').first().waitFor()

    await page.locator('.store-card').first().getByRole('button', { name: /^Додати в кошик:/ }).click()
    await nav.getByRole('button', { name: /Кошик/ }).click()
    await page.getByRole('heading', { name: 'Кошик', exact: true }).waitFor()
    await audit('cart')

    await nav.getByRole('button', { name: 'Чат', exact: true }).click()
    await page.waitForLoadState('networkidle')
    await audit('chat')

    await nav.getByRole('button', { name: 'Профіль', exact: true }).click()
    await page.waitForLoadState('networkidle')
    await audit('profile')
    await page.close()
  }
} finally { await browser.close() }
console.log(`MINIAPP A11Y MATRIX: ${checks - failures.length}/${checks}`)
if (failures.length) process.exitCode = 1
