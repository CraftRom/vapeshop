// Portable browser checks with neutral demo goods; all API traffic is intercepted.
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from 'playwright'
const output = process.env.QA_OUTPUT_DIR || new URL('./output/', import.meta.url).pathname
mkdirSync(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH, args: ['--no-sandbox', '--disable-dev-shm-usage'] } : {}) })
let checks = 0
const failures = []
const check = (value, label) => { checks++; console.log(`${value ? 'PASS' : 'FAIL'} ${label}`); if (!value) failures.push(label) }
const photo = (color, type) => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect width="400" height="400" fill="#f3f4f6"/>${type === 'bag' ? `<path d="M100 130h200l-15 200H115Z" fill="${color}"/><path d="M155 145V90a45 45 0 0 1 90 0v55" fill="none" stroke="${color}" stroke-width="16"/><path d="M150 190h100" stroke="#fff" stroke-opacity=".3" stroke-width="4"/>` : `<path d="M110 230v-60a90 90 0 0 1 180 0v60" fill="none" stroke="${color}" stroke-width="28"/><rect x="78" y="190" width="64" height="105" rx="28" fill="${color}"/><rect x="258" y="190" width="64" height="105" rx="28" fill="${color}"/>`}</svg>`)
const goods = [
  { id: 1, name: 'Тканинна сумка — м’ятна', price: '320', old_price: '400', is_sale: true, stock: 2, is_new: true, photo_url: photo('#63ad94', 'bag'), description: 'Містка повсякденна сумка. '.repeat(32) },
  { id: 2, name: 'Навушники — графітові', price: '890', stock: 5, photo_url: photo('#354657', 'headphones'), description: 'Зручні навушники для щоденного використання.' },
  { id: 3, name: 'Сумка — пісочна', price: '280', stock: 0, photo_url: photo('#c4ab86', 'bag') },
  { id: 4, name: 'Навушники — бежеві', price: '760', old_price: '900', is_sale: true, stock: 7, photo_url: photo('#c4ab86', 'headphones') },
  { id: 5, name: 'Подарункова сумка з дуже довгою назвою для перевірки вузького екрана', price: '410', stock: 4 },
  ...Array.from({ length: 7 }, (_, i) => ({ id: i + 6, name: `Аксесуар ${i + 1}`, price: String(200 + i * 10), stock: 8, photo_url: photo(i % 2 ? '#354657' : '#63ad94', i % 2 ? 'headphones' : 'bag') })),
]
try {
  for (const variant of [{ width: 320, scheme: 'dark' }, { width: 390, scheme: 'dark' }, { width: 900, scheme: 'dark' }, { width: 1280, scheme: 'dark' }, { width: 390, scheme: 'light' }, { width: 1280, scheme: 'light' }]) {
    const label = `${variant.width}px ${variant.scheme}`
    const context = await browser.newContext({ viewport: { width: variant.width, height: 760 } })
    const p = await context.newPage()
    const errors = []
    p.on('pageerror', error => { errors.push(error.message); console.log(`RUNTIME ERROR ${label}: ${error.message}`) })
    let cartQty = 0, failProducts = false, failCart = false
    const cart = () => ({ lines: cartQty ? [{ product_id: 1, name: goods[0].name, qty: cartQty, stock: 2, price: '320', line_total: String(cartQty * 320) }] : [], subtotal: String(cartQty * 320) })
    await p.addInitScript(scheme => {
      window.Telegram = { WebApp: { initData: 'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test', platform: 'tdesktop', colorScheme: scheme, initDataUnsafe: { user: { id: 123 } }, ready() {}, expand() {}, disableVerticalSwipes() {}, onEvent() {}, offEvent() {}, BackButton: { show() { window.__qaBackShown = true }, hide() { window.__qaBackShown = false }, onClick(callback) { window.__qaBack = callback }, offClick() {} } } }
    }, variant.scheme)
    await p.route('https://telegram.org/**', route => route.fulfill({ body: '' }))
    await p.route('**/api/**', async route => {
      const url = new URL(route.request().url()), path = url.pathname
      let data = []
      if (path.endsWith('/config')) data = { age_confirmed: true, min_age: 18, shop_name: 'Магазин', currency: 'грн', bonus_enabled: false, referral_enabled: false, delivery_methods: ['Нова пошта'], payment_methods: ['На рахунок'] }
      else if (path.endsWith('/cart')) {
        if (route.request().method() === 'POST') {
          if (failCart) { await route.fulfill({ status: 400, json: { detail: 'Демопомилка зміни кошика' } }); return }
          const body = route.request().postDataJSON()
          if (body.product_id === 1) cartQty = Math.max(0, Math.min(2, cartQty + body.delta))
        }
        data = cart()
      } else if (path.endsWith('/orders')) data = [{ id: 1, status: 'new', total: '320', items: [{ name: 'Тканинна сумка', qty: 1, price: '320' }], created_at: '2026-10-08T12:00:00Z' }]
      else if (path.endsWith('/chat')) {
        data = route.request().method() === 'POST' ? { id: 2, text: route.request().postDataJSON().text, direction: 'in', created_at: '2026-10-08T12:00:00Z' } : [{ id: 1, text: 'Вітаємо', direction: 'out', created_at: '2026-10-08T12:00:00Z' }]
      } else if (path.endsWith('/profile')) data = { first_name: 'Покупець', bonus_balance: '0', orders_count: 0 }
      else if (path.endsWith('/categories')) data = Array.from({ length: 18 }, (_, i) => ({ id: i + 1, name: i === 0 ? 'Аксесуари' : `Колекція ${i + 1}` }))
      else if (/\/products\/\d+$/.test(path)) data = goods.find(item => item.id === Number(path.split('/').pop()))
      else if (path.endsWith('/products')) {
        if (failProducts) { await route.fulfill({ status: 503, json: { detail: 'Каталог тимчасово недоступний' } }); return }
        const q = (url.searchParams.get('q') || url.searchParams.get('search') || '').toLowerCase()
        data = goods.filter(item => item.name.toLowerCase().includes(q))
      } else if (path.endsWith('/wishlists')) data = Array.from({ length: 25 }, (_, i) => ({ id: i + 1, name: `Список ${i + 1}`, product_ids: [], size: 0 }))
      await route.fulfill({ json: data })
    })
    await p.goto((process.env.MINIAPP_URL || 'http://127.0.0.1:5174') + '/app/')
    await p.locator('.store-card').first().waitFor()
    await p.locator('.store-card-image').first().evaluate(img => img.decode())
    check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${label}: no horizontal page overflow`)
    const columns = await p.locator('.product-grid').evaluate(e => getComputedStyle(e).gridTemplateColumns.split(' ').length)
    check(columns === (variant.width >= 1000 ? 4 : variant.width >= 700 ? 3 : 2), `${label}: responsive product columns`)
    check(await p.locator('.store-card-image').first().evaluate(e => getComputedStyle(e).objectFit === 'contain'), `${label}: photos are not cropped`)
    check(await p.locator('.store-card-discount').first().textContent() === '−20%', `${label}: exact discount percent`)
    await p.screenshot({ path: join(output, `catalog-${variant.width}-${variant.scheme}.png`) })
    const rail = p.getByRole('group', { name: 'Категорії', exact: true })
    await rail.hover(); await p.mouse.wheel(0, 360)
    await p.waitForFunction(() => document.querySelector('.store-categories').scrollLeft > 0)
    check(await rail.evaluate(e => e.scrollLeft > 0), `${label}: category wheel scrolling`)
    const sort = p.getByRole('button', { name: /^Сортування:/ })
    check(await sort.getAttribute('aria-label') === 'Сортування: Новинки' && await p.locator('.store-card').count() === 1, `${label}: initial catalog selects real new products`)
    await sort.click()
    let sheet = p.getByRole('dialog', { name: 'Сортування товарів' })
    await sheet.waitFor()
    const firstSort = sheet.getByRole('group', { name: 'Порядок товарів' }).getByRole('button').first()
    check(await firstSort.textContent() === 'Новинки' && await firstSort.getAttribute('aria-pressed') === 'true', `${label}: new products are first and selected`)
    await p.setViewportSize({ width: variant.width, height: 320 })
    await p.waitForFunction(() => document.querySelector('.sort-sheet').clientHeight <= innerHeight - 24)
    check(await sheet.evaluate(e => e.scrollHeight > e.clientHeight), `${label}: sort menu has bounded vertical scroll`)
    await sheet.hover(); await p.mouse.wheel(0, 700)
    await p.waitForFunction(() => document.querySelector('.sort-sheet').scrollTop > 0)
    check(await sheet.evaluate(e => e.scrollTop > 0), `${label}: last sort option is reachable`)
    const options = sheet.getByRole('button')
    await options.last().focus(); await p.keyboard.press('Tab')
    check(await options.first().evaluate(e => document.activeElement === e), `${label}: sort focus trap`)
    check(await p.evaluate(() => document.body.style.overflow === 'hidden'), `${label}: modal locks background`)
    await p.keyboard.press('Escape')
    check(await sheet.count() === 0 && await sort.evaluate(e => e === document.activeElement), `${label}: Escape restores focus`)
    await p.setViewportSize({ width: variant.width, height: 760 })
    await sort.click()
    await p.waitForFunction(() => window.__qaBackShown === true)
    await p.evaluate(() => window.__qaBack?.())
    await sheet.waitFor({ state: 'hidden' })
    check(await sheet.count() === 0, `${label}: Telegram Back closes sort menu`)
    await sort.click(); await p.getByRole('button', { name: 'За зростанням ціни', exact: true }).click()
    check(await p.locator('.store-card-title').first().textContent() === 'Аксесуар 1', `${label}: actual price sorting`)
    await sort.click(); await p.getByRole('button', { name: 'За алфавітом, Я–А', exact: true }).click()
    check((await p.locator('.store-card-title').first().textContent()).startsWith('Тканинна'), `${label}: Ukrainian alphabet sorting`)
    await sort.click(); await p.getByRole('button', { name: 'Акції', exact: true }).click()
    check(await p.locator('.store-card').count() === 2, `${label}: real discounts only`)
    await sort.click(); await p.getByRole('button', { name: 'Новинки', exact: true }).click()
    check(await p.locator('.store-card').count() === 1, `${label}: real new statuses only`)
    await p.getByRole('button', { name: 'Скинути фільтри', exact: true }).click()
    await p.getByRole('button', { name: 'В наявності', exact: true }).click()
    check(await p.locator('.store-card').count() === 11, `${label}: stock filter`)
    await p.getByRole('button', { name: 'Скинути фільтри', exact: true }).click()
    await p.getByRole('navigation', { name: 'Розділи магазину' }).getByRole('button', { name: 'Пошук', exact: true }).click()
    check(await p.getByRole('textbox', { name: 'Пошук товарів' }).evaluate(e => e === document.activeElement), `${label}: search navigation focuses input`)
    await p.getByRole('textbox', { name: 'Пошук товарів' }).fill('навушники')
    await p.waitForFunction(() => document.querySelectorAll('.store-card').length === 2)
    check(await p.locator('.store-card').count() === 2, `${label}: search results`)
    await p.getByRole('button', { name: 'Очистити', exact: true }).click()
    await p.locator('.store-card').nth(11).waitFor()
    await sort.click(); await p.getByRole('button', { name: 'Новинки', exact: true }).click()
    await p.getByRole('textbox', { name: 'Пошук товарів' }).fill('навушники')
    await p.getByRole('heading', { name: 'Нічого не знайшли' }).waitFor()
    await sort.click()
    check(await p.getByRole('button', { name: 'Новинки', exact: true }).getAttribute('aria-pressed') === 'true', `${label}: selected new option remains visible when no new products match`)
    await p.getByRole('button', { name: 'За порядком', exact: true }).click()
    check(await p.locator('.store-card').count() === 2, `${label}: all matching goods reachable from empty new view`)
    await p.getByRole('button', { name: 'Очистити', exact: true }).click()
    await p.locator('.store-card').nth(11).waitFor()
    await p.getByRole('button', { name: 'Відкласти', exact: true }).first().click()
    const saveSheet = p.getByRole('dialog', { name: 'Зберегти в список' })
    await saveSheet.waitFor()
    check(await saveSheet.evaluate(e => e.scrollHeight > e.clientHeight), `${label}: wishlist menu scrolls`)
    await p.keyboard.press('Escape')
    const first = p.locator('.store-card').first()
    await first.getByRole('button', { name: /^Додати в кошик:/ }).click()
    await first.getByRole('button', { name: 'Додати ще одну штуку', exact: true }).click()
    check(await first.getByRole('button', { name: 'Додати ще одну штуку', exact: true }).isDisabled(), `${label}: stock ceiling applies immediately`)
    await first.getByRole('button', { name: 'Прибрати одну штуку', exact: true }).click()
    await first.locator('.store-card-title').click()
    await p.getByRole('heading', { name: goods[0].name, exact: true }).waitFor()
    await p.getByRole('button', { name: 'Детальніше', exact: true }).click()
    check(await p.locator('.detail-description').evaluate(e => !e.classList.contains('is-collapsed')), `${label}: product description expands`)
    await p.getByRole('button', { name: 'Згорнути', exact: true }).click()
    check(await p.getByRole('button', { name: 'Детальніше' }).getAttribute('aria-expanded') === 'false', `${label}: product description collapses`)
    await p.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }))
    await p.screenshot({ path: join(output, `product-${variant.width}-${variant.scheme}.png`), fullPage: false })
    await p.getByRole('button', { name: 'Назад до каталогу' }).click()
    await p.locator('.store-card').nth(11).waitFor()
    check(await sort.getAttribute('aria-label') === 'Сортування: За порядком' && await p.locator('.store-card').count() === 12, `${label}: returning from a product preserves chosen sorting`)
    await p.locator('.store-card-title').nth(1).click()
    await p.getByRole('heading', { name: goods[1].name, exact: true }).waitFor()
    check(await p.locator('.viewed-rail .store-card').count() === 1, `${label}: recently viewed products exclude current product`)
    await p.locator('.viewed-rail .store-card-title').first().click()
    await p.getByRole('heading', { name: goods[0].name, exact: true }).waitFor()
    check(await p.locator('.detail-title').textContent() === goods[0].name, `${label}: viewed product reopens with refreshed API data`)
    await p.getByRole('button', { name: 'Більше', exact: true }).click()
    await p.getByRole('button', { name: 'До кошика', exact: true }).click()
    await p.getByRole('heading', { name: 'Кошик', exact: true }).waitFor()
    check(await p.locator('.cart-stepper .qty').textContent() === '2', `${label}: cart navigation waits for pending updates`)
    check(await p.locator('.bar').evaluate(e => e.getBoundingClientRect().bottom <= document.querySelector('.store-nav').getBoundingClientRect().top + 1), `${label}: checkout bar does not overlap bottom navigation`)
    await p.getByRole('navigation').getByRole('button', { name: 'Чат', exact: true }).click()
    check(await p.locator('.bar').isHidden(), `${label}: cart bar hidden in chat`)
    await p.locator('.chat-pick').first().click()
    const message = p.getByPlaceholder('Повідомлення менеджеру')
    await message.waitFor()
    check(await p.locator('.chat-compose').evaluate(e => e.getBoundingClientRect().bottom <= document.querySelector('.store-nav').getBoundingClientRect().top + 1), `${label}: chat composer clears bottom navigation`)
    await message.fill('Дякую')
    await p.getByRole('button', { name: 'Надіслати', exact: true }).click()
    await p.locator('.chat-log .bubble-text').filter({ hasText: 'Дякую' }).waitFor()
    check(await message.inputValue() === '', `${label}: chat send clears input`)
    await p.getByRole('navigation').getByRole('button', { name: 'Профіль', exact: true }).click()
    await p.getByRole('heading', { name: 'Профіль', exact: true }).waitFor()
    check(await p.getByRole('heading', { name: 'Профіль', exact: true }).isVisible(), `${label}: profile navigation`)
    await p.getByRole('navigation').getByRole('button', { name: 'Каталог', exact: true }).click()
    await p.locator('.store-card').first().waitFor()
    failProducts = true
    await p.getByRole('button', { name: 'Аксесуари', exact: true }).click()
    await p.getByRole('heading', { name: 'Не вдалося завантажити каталог' }).waitFor()
    check(await p.locator('.skeleton').count() === 0, `${label}: failed request ends loading`)
    failProducts = false
    await p.getByRole('button', { name: 'Повторити', exact: true }).click()
    await p.locator('.store-card').first().waitFor()
    check(await p.getByRole('heading', { name: 'Не вдалося завантажити каталог' }).count() === 0, `${label}: retry recovers`)
    await p.locator('.store-card-title').first().click()
    await p.getByRole('button', { name: 'Назад до каталогу' }).click()
    check(await p.getByRole('button', { name: 'Аксесуари', exact: true }).getAttribute('aria-pressed') === 'true', `${label}: product back keeps catalog category`)
    await p.locator('.store-card-title').first().click()
    failCart = true
    await p.getByRole('button', { name: 'Менше', exact: true }).click()
    await p.getByRole('alert').filter({ hasText: 'Демопомилка зміни кошика' }).waitFor()
    check(await p.getByRole('alert').filter({ hasText: 'Демопомилка зміни кошика' }).isVisible(), `${label}: cart errors visible on product page`)
    check(!errors.length, `${label}: no React runtime errors ${errors.join('; ')}`)
    await context.close()
  }
} finally { await browser.close() }
console.log(`STOREFRONT BROWSER: ${checks - failures.length}/${checks}`)
if (failures.length) process.exitCode = 1
