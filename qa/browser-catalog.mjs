// Catalog lifecycle and dashboard/storefront parity with shared neutral fixtures.
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
const output = process.env.QA_OUTPUT_DIR || new URL('./output/', import.meta.url).pathname
mkdirSync(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH, args: ['--no-sandbox', '--disable-dev-shm-usage'] } : {}) })
let checks = 0; const failures = []
const check = (ok, label) => { checks++; console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`); if (!ok) failures.push(label) }
const photo = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" rx="20" fill="#63ad94"/></svg>')
try {
 for (const width of [360, 1280]) {
  const context = await browser.newContext({ viewport: { width, height: 760 } })
  const errors = [], writes = []
  let holdDescription = false, descriptionHeld, releaseDescription
  const roots = [{ id: 1, name: 'Аксесуари', is_active: true, products_count: 1 }, { id: 2, name: 'Подарунки', is_active: true, products_count: 0 }]
  const subs = [{ id: 1, name: 'Сумки', category_id: 1, category_name: 'Аксесуари', is_active: true, products_count: 0 }, { id: 2, name: 'Окрема група', category_id: null, is_active: true, products_count: 0 }]
  const goods = [{ id: 1, name: 'Товар без груп', price: '50', stock: 1, category_id: null, subcategory_id: null, sku: 'ELF-GEN-TEST0001', is_active: true, is_new: false, is_sale: false }]
  const hydrate = (p) => ({ ...p, category_name: roots.find(c => c.id === p.category_id)?.name || null, subcategory_name: subs.find(s => s.id === p.subcategory_id)?.name || null, has_photo: Boolean(p.photo_url) })
  await context.addInitScript(() => {
   sessionStorage.setItem('shop_dashboard_token', 'qa'); sessionStorage.setItem('shop_dashboard_session', JSON.stringify({ role: 'admin', name: 'QA' }))
   window.Telegram = { WebApp: { initData: 'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test', platform: 'tdesktop', colorScheme: 'dark', initDataUnsafe: { user: { id: 123 } }, ready() {}, expand() {}, disableVerticalSwipes() {}, onEvent() {}, offEvent() {}, BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} } } }
  })
  await context.route('https://telegram.org/**', route => route.fulfill({ body: '' }))
  await context.route('**/api/**', async route => {
   const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
   let data = [], status = 200
   if (path.endsWith('/subcategories')) {
    if (method === 'POST') { const group = request.postDataJSON(); subs.push({ ...group, id: subs.length + 1, category_name: roots.find(c => c.id === group.category_id)?.name || null, products_count: 0 }); writes.push(group); data = subs.at(-1) }
    else data = subs
   } else if (path.endsWith('/categories')) {
    if (method === 'POST') { roots.push({ ...request.postDataJSON(), id: roots.length + 1, products_count: 0 }); data = roots.at(-1) }
    else data = roots
   } else if (/\/products\/\d+$/.test(path)) {
    const item = goods.find(p => p.id === Number(path.split('/').pop()))
    if (method === 'PATCH') {
     const body = request.postDataJSON(), merged = { ...item, ...body }; writes.push(body)
     if (merged.is_sale && Number(merged.old_price) <= Number(merged.price)) { status = 400; data = { detail: 'Для акції стара ціна має бути більшою за поточну' } }
     else { Object.assign(item, body); data = hydrate(item) }
     if (holdDescription && 'description' in body) {
      await new Promise(resolve => { releaseDescription = resolve; descriptionHeld() })
     }
    } else data = hydrate(item)
   } else if (path.endsWith('/products')) {
    if (method === 'POST') { const body = request.postDataJSON(); writes.push(body); const id = goods.length + 1; goods.push({ ...body, id, sku: `ELF-GEN-TEST000${id}` }); data = hydrate(goods.at(-1)); status = 201 }
    else {
     const cid = Number(url.searchParams.get('category_id')), sid = Number(url.searchParams.get('subcategory_id')), search = (url.searchParams.get('search') || '').toLowerCase()
     data = goods.filter(p => (!path.includes('/shop/') || p.is_active) && (!cid || p.category_id === cid || subs.find(s => s.id === p.subcategory_id)?.category_id === cid) && (!sid || p.subcategory_id === sid) && (!search || p.name.toLowerCase().includes(search) || p.sku.toLowerCase().includes(search)) && (!url.searchParams.has('is_new') || p.is_new) && (!url.searchParams.has('is_sale') || p.is_sale) && (!url.searchParams.has('uncategorized') || !p.category_id && !p.subcategory_id)).map(hydrate)
    }
   } else if (path.endsWith('/config')) data = { age_confirmed: true, min_age: 18, shop_name: 'Магазин', currency: 'грн', bonus_enabled: false, referral_enabled: false }
   else if (path.endsWith('/cart')) data = { lines: [], subtotal: '0' }
   else if (path.endsWith('/profile')) data = { first_name: 'QA', bonus_balance: '0', orders_count: 0 }
   else if (path.includes('notifications')) data = { items: [], unread: 0 }
   else if (path.includes('badges')) data = { orders_new: 0, support_unread: 0 }
   await route.fulfill({ status, json: data })
  })
  const p = await context.newPage(); p.on('pageerror', e => errors.push(e.message))
  await p.goto('http://127.0.0.1:5173/catalog')
  await p.locator('.catalog-product').first().waitFor()
  await p.locator('.catalog-add-btn').click()
  const modal = p.getByRole('dialog', { name: 'Новий товар', exact: true })
  await modal.waitFor()
  check(await modal.getByLabel('Категорія товару', { exact: true }).inputValue() === '' && await modal.getByLabel('Субкатегорія товару', { exact: true }).inputValue() === '', `${width}: new form permits no groups`)
  check(await modal.getByText('Артикул (SKU) · автоматично').isVisible() && !(await modal.locator('input[aria-label="SKU"]').count()), `${width}: article is automatic`)
  await modal.getByLabel('Назва товару', { exact: true }).fill('М’ятна сумка')
  await modal.getByLabel('Ціна товару', { exact: true }).fill('199.90')
  await modal.getByLabel('Залишок товару', { exact: true }).fill('5')
  await p.getByRole('button', { name: 'Створити товар', exact: true }).click()
  await p.waitForURL('**/catalog/products/2')
  await p.getByRole('heading', { name: 'М’ятна сумка', exact: true }).waitFor()
  check(goods[1].category_id === null && goods[1].subcategory_id === null && !('sku' in writes[0]), `${width}: create payload has nullable taxonomy and no manual SKU`)
  check(await p.getByText('ELF-GEN-TEST0002', { exact: true }).isVisible(), `${width}: generated SKU is prominent`)
  const groupBlock = p.getByRole('region', { name: 'Категорія та субкатегорія', exact: true })
  await groupBlock.getByRole('button', { name: 'Редагувати', exact: true }).click()
  await groupBlock.getByLabel('Субкатегорія товару', { exact: true }).selectOption('1')
  await groupBlock.getByRole('button', { name: 'Зберегти блок' }).click()
  await groupBlock.getByRole('button', { name: 'Редагувати', exact: true }).waitFor()
  check(goods[1].category_id === null && goods[1].subcategory_id === 1, `${width}: only a subcategory can be saved`)
  const description = p.getByRole('region', { name: 'Опис', exact: true })
  await description.getByRole('button', { name: 'Редагувати', exact: true }).click()
  await description.getByLabel('Опис товару', { exact: true }).fill('Містка сумка.\nКолір: м’ятний.')
  await description.getByRole('button', { name: 'Зберегти блок' }).click()
  await description.getByRole('button', { name: 'Редагувати', exact: true }).waitFor()
  check(Object.keys(writes.at(-1)).join() === 'description', `${width}: description saves only its block`)
  const prices = p.getByRole('region', { name: 'Ціни та акція', exact: true })
  await prices.getByRole('button', { name: 'Редагувати', exact: true }).click()
  await prices.getByLabel('Стара ціна товару', { exact: true }).fill('150')
  await prices.getByRole('checkbox').check()
  await prices.getByRole('button', { name: 'Зберегти блок' }).click()
  await prices.getByRole('alert').waitFor()
  check(goods[1].is_sale === false && await prices.getByLabel('Стара ціна товару', { exact: true }).inputValue() === '150', `${width}: failed save keeps form and prior data`)
  await prices.getByLabel('Стара ціна товару', { exact: true }).fill('249.90')
  await prices.getByRole('button', { name: 'Зберегти блок' }).click()
  await prices.getByRole('button', { name: 'Редагувати', exact: true }).waitFor()
  holdDescription = true
  const held = new Promise(resolve => { descriptionHeld = resolve })
  await description.getByRole('button', { name: 'Редагувати', exact: true }).click()
  await description.getByRole('button', { name: 'Зберегти блок' }).click()
  await held
  const display = p.getByRole('region', { name: 'Основне та відображення', exact: true })
  await display.getByRole('button', { name: 'Редагувати', exact: true }).click()
  await display.getByRole('checkbox', { name: /^Новинка/ }).check()
  await display.getByRole('button', { name: 'Зберегти блок' }).click()
  await display.getByRole('button', { name: 'Редагувати', exact: true }).waitFor()
  holdDescription = false; releaseDescription()
  await description.getByRole('button', { name: 'Редагувати', exact: true }).waitFor()
  check((await display.textContent()).includes('Новинка ·') && (await description.textContent()).includes('Колір: м’ятний.'), `${width}: out-of-order block responses retain both saved changes`)
  const image = p.getByRole('region', { name: 'Зображення', exact: true })
  await image.getByRole('button', { name: 'Редагувати', exact: true }).click()
  await image.getByPlaceholder('або вставте пряме посилання').fill(photo)
  await image.getByRole('button', { name: 'Зберегти блок' }).click()
  await image.getByRole('button', { name: 'Редагувати', exact: true }).waitFor()
  check(Object.keys(writes.at(-1)).join() === 'photo_url' && goods[1].is_new && goods[1].is_sale && goods[1].sku === 'ELF-GEN-TEST0002', `${width}: photo block preserves flags and article`)
  check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}: product editor has no horizontal overflow`)
  await p.evaluate(() => { window.scrollTo(0, 0); return new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))) })
  await p.screenshot({ path: join(output, `catalog-editor-${width}.png`), fullPage: true })
  await p.getByRole('link', { name: '← До каталогу', exact: true }).click()
  await p.getByLabel('Фільтр відображення').selectOption('new')
  await p.waitForFunction(() => document.querySelectorAll('.catalog-product').length === 1)
  check((await p.locator('.catalog-product').textContent()).includes('М’ятна сумка'), `${width}: dashboard novelty filter uses saved status`)
  await p.locator('.catalog-categories-btn').click()
  await p.getByRole('button', { name: 'Нова категорія', exact: true }).click()
  await p.getByLabel('Назва групи').fill('Колекції')
  await p.getByRole('dialog', { name: 'Нова категорія', exact: true }).getByRole('button', { name: 'Зберегти', exact: true }).click()
  await p.getByRole('dialog', { name: 'Нова категорія', exact: true }).waitFor({ state: 'hidden' })
  check(roots.some(c => c.name === 'Колекції'), `${width}: new root category works`)
  await p.getByRole('button', { name: 'Нова субкатегорія', exact: true }).click()
  await p.getByLabel('Назва групи').fill('Літня колекція')
  await p.getByLabel('Батьківська категорія', { exact: true }).selectOption('3')
  await p.getByRole('dialog', { name: 'Нова субкатегорія', exact: true }).getByRole('button', { name: 'Зберегти', exact: true }).click()
  await p.getByRole('dialog', { name: 'Нова субкатегорія', exact: true }).waitFor({ state: 'hidden' })
  check(subs.some(s => s.name === 'Літня колекція' && s.category_id === 3), `${width}: new subcategory retains its parent`)
  await p.getByRole('dialog', { name: 'Категорії та субкатегорії', exact: true }).locator('footer').getByRole('button', { name: 'Закрити', exact: true }).click()
  const store = await context.newPage(); store.on('pageerror', e => errors.push(e.message))
  await store.goto('http://127.0.0.1:5174/app/')
  await store.locator('.store-card').first().waitFor()
  check(await store.locator('.store-card-new').count() === 1 && await store.locator('.store-card-discount').count() === 1, `${width}: storefront badges match dashboard`)
  await store.getByRole('group', { name: 'Категорії', exact: true }).getByRole('button', { name: 'Аксесуари', exact: true }).click()
  await store.waitForFunction(() => document.querySelectorAll('.store-card').length === 1)
  check(await store.locator('.store-card-title').textContent() === 'М’ятна сумка', `${width}: parent shows subcategory-only product`)
  await store.getByRole('group', { name: 'Субкатегорії', exact: true }).getByRole('button', { name: 'Сумки', exact: true }).click()
  await store.locator('.store-card-title').click()
  await store.getByRole('heading', { name: 'М’ятна сумка', exact: true }).waitFor()
  check(await store.getByText('ELF-GEN-TEST0002', { exact: true }).isVisible(), `${width}: storefront shows the same SKU`)
  check((await store.locator('.detail-price').textContent()).includes('199,9') && (await store.locator('.detail-description').textContent()).includes('Колір: м’ятний.'), `${width}: prices and description match saved blocks`)
  await store.screenshot({ path: join(output, `catalog-parity-${width}.png`), fullPage: true })
  await store.getByRole('button', { name: 'Назад до каталогу', exact: true }).click()
  await store.getByRole('button', { name: 'Без груп', exact: true }).click()
  await store.getByRole('button', { name: 'Товар без груп', exact: true }).waitFor()
  check(await store.locator('.store-card-title').textContent() === 'Товар без груп', `${width}: completely ungrouped goods remain visible`)
  check(!errors.length, `${width}: no runtime errors: ${errors.join('; ')}`)
  await context.close()
 }
} finally { await browser.close() }
writeFileSync(join(output, 'catalog-browser-results.json'), JSON.stringify({ checks, failures }, null, 2))
console.log(`CATALOG BROWSER: ${checks - failures.length}/${checks}`)
if (failures.length) process.exit(1)
