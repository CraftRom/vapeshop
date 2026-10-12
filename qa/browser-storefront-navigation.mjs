// Regression for the real React storefront; neutral demo fixtures and intercepted API.
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
const output = process.env.QA_OUTPUT_DIR || new URL('./output/', import.meta.url).pathname
mkdirSync(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH, args: ['--no-sandbox', '--disable-dev-shm-usage'] } : {}) })
let checks = 0
const failures = []
const check = (ok, label) => { checks++; console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`); if (!ok) failures.push(label) }
try {
  for (const variant of [{ width: 320, scheme: 'dark' }, { width: 390, scheme: 'light' }, { width: 1280, scheme: 'dark' }]) {
    const label = `${variant.width}px ${variant.scheme}`
    const context = await browser.newContext({ viewport: { width: variant.width, height: 820 } })
    const p = await context.newPage(), errors = [], requests = []
    p.on('pageerror', error => errors.push(error.message))
    let categoryFailure = false, delayedCategory = false, large = false
    const categories = [{ id: 1, name: 'Аксесуари', products_count: 4 }, { id: 2, name: 'Подарунки', products_count: 2 }, { id: 3, name: 'Порожній розділ', products_count: 0 }, ...Array.from({ length: 14 }, (_, i) => ({ id: i + 4, name: `Колекція ${i + 4}`, products_count: 0 }))]
    const subs = [{ id: 11, name: 'Сумки', category_id: 1, products_count: 2 }, { id: 12, name: 'Навушники з довгою назвою для перевірки перенесення тексту', category_id: 1, products_count: 1 }, { id: 21, name: 'Подарункові набори', category_id: 2, products_count: 1 }, { id: 31, name: 'Самостійна група', category_id: null, products_count: 1 }]
    const photo = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" rx="20" fill="#63ad94"/><path d="M60 70h80v90H60Z M80 70V55h40v15" fill="none" stroke="#fff" stroke-width="7"/></svg>')
    const goods = [
      { id: 1, name: 'Звичайний подарунок', category_id: 2, price: '40', stock: 2 },
      { id: 2, name: 'Нова сумка', subcategory_id: 11, is_new: true, price: '300', stock: 5 },
      { id: 3, name: 'Звичайні навушники', subcategory_id: 12, price: '500', stock: 4 },
      { id: 4, name: 'Акційна сумка', subcategory_id: 11, price: '250', old_price: '400', is_sale: true, stock: 2 },
      { id: 5, name: 'Сумка без залишку', category_id: 1, price: '150', stock: 0 },
      { id: 6, name: 'Самостійний товар', subcategory_id: 31, price: '180', stock: 3 },
      { id: 7, name: 'Товар без груп', price: '60', stock: 1 },
      { id: 8, name: 'Акційний набір', subcategory_id: 21, price: '150', old_price: '200', is_sale: true, stock: 4 },
    ].map(item => ({ category_id: null, subcategory_id: null, ...item, sku: `ELF-${item.id}`, photo_url: photo }))
    await p.addInitScript(scheme => {
      window.Telegram = { WebApp: { initData: 'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test', platform: 'tdesktop', colorScheme: scheme, initDataUnsafe: { user: { id: 123 } }, ready() {}, expand() {}, disableVerticalSwipes() {}, onEvent(name, callback) { (window.__qaEvents ||= {})[name] = callback }, offEvent() {}, BackButton: { show() {}, hide() {}, onClick(callback) { window.__qaBack = callback }, offClick() {} } } }
    }, variant.scheme)
    await p.route('https://telegram.org/**', route => route.fulfill({ body: '' }))
    await p.route('**/api/**', async route => {
      const url = new URL(route.request().url()), path = url.pathname
      let data = []
      if (path.endsWith('/config')) data = { age_confirmed: true, shop_name: 'Магазин', currency: 'грн', bonus_enabled: false, referral_enabled: false }
      else if (path.endsWith('/cart')) data = { lines: [], subtotal: '0' }
      else if (path.endsWith('/profile')) data = { first_name: 'QA', bonus_balance: '0' }
      else if (path.endsWith('/categories')) {
        if (categoryFailure) { await route.fulfill({ status: 503, json: { detail: 'Демопомилка категорій' } }); return }
        data = categories
      } else if (path.endsWith('/subcategories')) data = subs
      else if (/\/products\/\d+$/.test(path)) data = goods.find(item => item.id === Number(path.split('/').pop()))
      else if (path.endsWith('/products')) {
        const query = Object.fromEntries(url.searchParams); requests.push(query)
        const cid = Number(query.category_id), sid = Number(query.subcategory_id), search = (query.search || '').toLowerCase()
        const source = large ? Array.from({ length: 503 }, (_, i) => ({ ...goods[6], id: i + 1000, name: `Великий каталог ${i}`, is_new: i === 502 })) : goods
        const rows = source.filter(item => (!cid || item.category_id === cid || subs.find(sub => sub.id === item.subcategory_id)?.category_id === cid) && (!sid || item.subcategory_id === sid) && (!query.uncategorized || !item.category_id && !item.subcategory_id) && (!search || item.name.toLowerCase().includes(search) || item.sku.toLowerCase().includes(search)))
        data = rows.slice(Number(query.offset || 0), Number(query.offset || 0) + Number(query.limit || 500))
        if (delayedCategory && cid === 1) await new Promise(resolve => setTimeout(resolve, 500))
      }
      await route.fulfill({ json: data })
    })
    const titles = () => p.locator('.store-card-title').allTextContents()
    const waitCount = count => p.waitForFunction(n => document.querySelectorAll('.store-card').length === n, count)
    const root = name => p.getByRole('group', { name: 'Категорії', exact: true }).getByRole('button', { name, exact: true })
    const sub = name => p.getByRole('group', { name: 'Субкатегорії', exact: true }).getByRole('button', { name, exact: true })
    const sort = value => p.getByRole('button', { name: /^Сортування:/ }).click().then(() => p.getByRole('dialog', { name: 'Сортування товарів' }).getByRole('button', { name: value, exact: true }).click())
    await p.goto((process.env.MINIAPP_URL || 'http://127.0.0.1:5174') + '/app/')
    await waitCount(8)
    check((await titles())[0] === 'Нова сумка', `${label}: new goods first, entire assortment visible`)
    check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${label}: no page overflow`)
    await p.screenshot({ path: join(output, `navigation-${variant.width}-${variant.scheme}.png`) })
    check(!await p.locator('.store-catalog-tools').getByRole('button', { name: 'Без категорії', exact: true }).count(), `${label}: taxonomy never appears as an availability filter`)
    check(await p.getByRole('group', { name: 'Наявність товарів' }).getByRole('button', { name: 'Усі', exact: true }).getAttribute('aria-pressed') === 'true', `${label}: availability explicitly defaults to all goods`)
    check(!await p.locator('.category-tile-detail').filter({ hasText: 'Самостійна група' }).count(), `${label}: category cards have customer-facing labels`)
    const palette = await p.evaluate(() => { const css = getComputedStyle(document.documentElement); return { accent: css.getPropertyValue('--accent').trim(), page: css.getPropertyValue('--tg-bg').trim() } })
    check(palette.accent === (variant.scheme === 'dark' ? '#8b7bf0' : '#6453c6') && palette.page === (variant.scheme === 'dark' ? '#100e18' : '#ffffff'), `${label}: system palette matches the dashboard brand`)
    await p.evaluate(() => { window.Telegram.WebApp.themeParams = { bg_color: '#ff0000', text_color: '#ff0000', secondary_bg_color: '#ff0000' }; window.__qaEvents.themeChanged?.() })
    check(await p.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--tg-bg').trim()) === palette.page, `${label}: custom Telegram colours cannot break brand text contrast`)
    if (variant.width >= 700) {
      await p.getByRole('button', { name: 'Наступні категорії' }).click()
      await p.waitForFunction(() => document.querySelector('.store-categories').scrollLeft > 0)
      await p.waitForFunction(() => !document.querySelector('[aria-label="Попередні категорії"]').disabled)
      check(await p.getByRole('button', { name: 'Попередні категорії' }).isEnabled(), `${label}: desktop category arrows work`)
    }

    await sort('Спочатку акції')
    check((await titles()).slice(0, 2).join() === 'Акційна сумка,Акційний набір' && (await titles()).length === 8, `${label}: sales first, ordinary goods retained`)
    await root('Подарунки').click(); await waitCount(2)
    await sort('Спочатку новинки')
    check((await titles()).length === 2, `${label}: category without new goods is not empty`)
    check(await sub('Подарункові набори').isVisible() && !await p.getByRole('group', { name: 'Субкатегорії', exact: true }).getByRole('button', { name: 'Самостійна група', exact: true }).count(), `${label}: only current parent's children appear`)
    await root('Аксесуари').click(); await waitCount(4)
    await sub('Сумки').click(); await waitCount(2)
    check((await p.getByRole('navigation', { name: 'Шлях категорії' }).textContent()).includes('АксесуариСумки'), `${label}: category path is visible`)
    await p.getByRole('textbox', { name: 'Пошук товарів' }).fill('неіснуючий товар')
    await p.getByRole('heading', { name: 'Нічого не знайшли' }).waitFor()
    check(await p.getByRole('button', { name: 'Прибрати фільтр пошуку' }).isVisible(), `${label}: search condition is visible and removable`)
    await p.getByRole('button', { name: 'Показати всі товари розділу' }).click(); await waitCount(2)
    check(await sub('Сумки').getAttribute('aria-pressed') === 'true', `${label}: clearing refinements preserves the subcategory`)
    await p.getByRole('button', { name: 'Скинути фільтри', exact: true }).click(); await waitCount(8)
    check(await root('Усе').getAttribute('aria-pressed') === 'true', `${label}: full reset clears category and subcategory`)
    await p.getByRole('textbox', { name: 'Пошук товарів' }).fill('навушники'); await waitCount(1)
    check((await titles())[0] === 'Звичайні навушники', `${label}: ordinary search match visible in novelty order`)
    await p.getByRole('button', { name: 'Прибрати фільтр пошуку' }).click(); await waitCount(8)
    await p.getByRole('button', { name: 'В наявності', exact: true }).click()
    check((await titles()).length === 7, `${label}: stock is the only inventory filter`)
    await p.getByRole('button', { name: 'В наявності', exact: true }).click()
    check((await titles()).length === 7 && await p.getByRole('button', { name: 'В наявності', exact: true }).getAttribute('aria-pressed') === 'true', `${label}: selecting stock twice is idempotent`)
    await root('Аксесуари').click(); await waitCount(3)
    await p.getByRole('group', { name: 'Наявність товарів' }).getByRole('button', { name: 'Усі', exact: true }).click(); await waitCount(4)
    check(await root('Аксесуари').getAttribute('aria-pressed') === 'true', `${label}: availability all preserves the category`)
    await root('Усе').click(); await waitCount(8)
    await p.getByRole('button', { name: 'В наявності', exact: true }).click()

    await p.getByRole('button', { name: 'Прибрати фільтр наявності' }).click(); await waitCount(8)
    await p.getByRole('button', { name: 'Усі категорії', exact: true }).click()
    const picker = p.getByRole('dialog', { name: 'Категорії та підкатегорії' })
    await picker.waitFor()
    check(await p.evaluate(() => document.body.style.overflow === 'hidden'), `${label}: category picker locks background`)
    const giftToggle = picker.getByRole('button', { name: 'Підкатегорії: Подарунки', exact: true })
    check(await giftToggle.getAttribute('aria-expanded') === 'false' && !await picker.getByRole('button', { name: 'Подарункові набори', exact: true }).isVisible(), `${label}: unopened category children are collapsed`)
    await giftToggle.click()
    check(await giftToggle.getAttribute('aria-expanded') === 'true' && await picker.getByRole('button', { name: 'Подарункові набори', exact: true }).isVisible(), `${label}: expanding a category reveals its subcategories`)
    await giftToggle.click()

    await p.setViewportSize({ width: variant.width, height: 360 })
    await p.waitForFunction(() => document.querySelector('.category-sheet').clientHeight <= innerHeight - 24)
    check(await picker.evaluate(element => element.scrollHeight > element.clientHeight && element.clientHeight <= innerHeight - 24), `${label}: long category tree has bounded scroll`)
    await picker.getByRole('textbox', { name: 'Пошук категорій' }).fill('навушники')
    check(await picker.getByRole('button', { name: 'Аксесуари', exact: true }).count() === 1 && await picker.getByRole('button', { name: 'Сумки', exact: true }).count() === 0, `${label}: category search retains matching child's parent`)
    await picker.getByRole('button', { name: subs[1].name, exact: true }).click(); await waitCount(1)
    check(await root('Аксесуари').getAttribute('aria-pressed') === 'true', `${label}: picker child sets its parent atomically`)
    await p.setViewportSize({ width: variant.width, height: 820 })
    await p.getByRole('button', { name: 'Усі категорії', exact: true }).click(); await picker.waitFor()
    await p.screenshot({ path: join(output, `category-picker-${variant.width}-${variant.scheme}.png`) })
    await picker.getByRole('button', { name: 'Самостійна група', exact: true }).click(); await waitCount(1)
    await p.getByRole('button', { name: 'Самостійний товар', exact: true }).waitFor()
    check((await titles())[0] === 'Самостійний товар' && !requests.at(-1).category_id, `${label}: independent group never combines with parent`)
    await p.getByRole('button', { name: 'Без категорії', exact: true }).click(); await waitCount(1)
    await p.getByRole('button', { name: 'Товар без груп', exact: true }).waitFor()
    check((await titles())[0] === 'Товар без груп' && requests.at(-1).uncategorized === 'true' && !requests.at(-1).subcategory_id, `${label}: ungrouped excludes taxonomy selection`)
    await root('Порожній розділ').click()
    await p.getByRole('heading', { name: 'Нічого не знайшли' }).waitFor()
    check(await p.getByRole('button', { name: 'Скинути пошук і фільтри' }).isVisible(), `${label}: truly empty category always has reset`)
    await p.getByRole('button', { name: 'Скинути пошук і фільтри' }).click(); await waitCount(8)
    delayedCategory = true
    await root('Аксесуари').click()
    await p.waitForFunction(() => document.querySelector('.product-grid[aria-busy="true"]'))
    await root('Подарунки').click(); await waitCount(2)
    await p.waitForTimeout(650)
    check((await titles()).join() === 'Звичайний подарунок,Акційний набір', `${label}: late request cannot overwrite current category`)
    delayedCategory = false
    await root('Аксесуари').click(); await waitCount(4)
    await sub('Сумки').click(); await waitCount(2)
    await p.locator('.store-card-title').first().click()
    await p.getByRole('button', { name: 'Назад до каталогу' }).waitFor()
    subs.splice(0, 1)
    await p.getByRole('button', { name: 'Назад до каталогу' }).click(); await waitCount(2)
    check(!requests.at(-1).subcategory_id && requests.at(-1).category_id === '1', `${label}: deleted saved subcategory cannot lock catalog`)
    await sub(subs[0].name).click(); await waitCount(1)
    await p.locator('.store-card-title').click(); await p.getByRole('button', { name: 'Назад до каталогу' }).waitFor()
    subs[0].category_id = 2
    await p.getByRole('button', { name: 'Назад до каталогу' }).click(); await waitCount(1)
    check(requests.at(-1).category_id === '2' && requests.at(-1).subcategory_id === '12', `${label}: moved saved group uses new parent`)
    await p.locator('.store-card-title').click(); await p.getByRole('button', { name: 'Назад до каталогу' }).waitFor()
    categories.splice(1, 1)
    await p.getByRole('button', { name: 'Назад до каталогу' }).click(); await waitCount(8)
    check(!requests.at(-1).category_id && !requests.at(-1).subcategory_id, `${label}: deleted parent and orphaned selection reset before products request`)
    categoryFailure = true
    await p.reload(); await p.getByRole('button', { name: 'Повторити завантаження категорій' }).waitFor()
    check(await p.getByRole('alert').filter({ hasText: 'Демопомилка категорій' }).isVisible(), `${label}: category failure is actionable`)
    categoryFailure = false
    await p.getByRole('button', { name: 'Повторити завантаження категорій' }).click(); await waitCount(8)
    categories.splice(0)
    await p.reload(); await waitCount(8)
    check(await root('Самостійна група').isVisible(), `${label}: legacy standalone groups have category cards without roots`)
    await root('Самостійна група').click()
    await p.getByRole('button', { name: 'Самостійний товар', exact: true }).waitFor()
    check(await root('Самостійна група').getAttribute('aria-pressed') === 'true' && !requests.at(-1).category_id, `${label}: standalone category card selects directly`)
    large = true
    await p.reload(); await waitCount(503)
    check((await titles())[0] === 'Великий каталог 502' && requests.some(query => query.offset === '500'), `${label}: more than 500 goods loaded, final-page novelty first`)
    check(!errors.length, `${label}: no runtime errors: ${errors.join('; ')}`)
    await context.close()
  }
} finally { await browser.close() }
writeFileSync(join(output, 'storefront-navigation-results.json'), JSON.stringify({ checks, failures }, null, 2))
console.log(`STOREFRONT NAVIGATION: ${checks - failures.length}/${checks}`)
if (failures.length) process.exit(1)
