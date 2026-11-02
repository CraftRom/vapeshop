import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH, args: ['--no-sandbox', '--disable-dev-shm-usage'] })
let checks = 0
const check = (value, label) => { if (!value) throw new Error(label); checks++; console.log(`PASS ${label}`) }
try {
  for (const [width, timezoneId] of [[320, 'Asia/Tokyo'], [390, 'America/New_York'], [1280, 'UTC']]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, timezoneId })
    const errors = []; page.on('pageerror', (e) => errors.push(e.message))
    const categories = [
      { id: 1, name: 'Рідини', is_active: true, products_count: 12 },
      { id: 2, name: 'Пристрої', is_active: true, products_count: 7 },
      { id: 3, name: 'Аксесуари', is_active: false, products_count: 5 },
    ]
    const promos = []; let writes = 0; let fail = true; let release; let lastBody; let categoryFail = width === 1280
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname, method = route.request().method()
      let data = {}
      if (path.endsWith('/auth/session')) data = { role: 'admin', name: 'QA', csrf_token: 'qa' }
      else if (path.endsWith('/catalog/categories')) {
        if (categoryFail) return route.fulfill({ status: 503, json: { detail: 'Категорії тимчасово недоступні' } })
        data = categories
      } else if (path.includes('/promos') && ['POST', 'PUT'].includes(method)) {
        writes++; lastBody = route.request().postDataJSON()
        check(route.request().headers()['x-csrf-token'] === 'qa', `${width}: CSRF preserved`)
        if (fail) { fail = false; return route.fulfill({ status: 409, json: { detail: 'Промокод із таким кодом уже існує' } }) }
        await new Promise((resolve) => { release = resolve })
        if (method === 'POST') { data = { ...lastBody, id: 1, used_count: 0, expires_at: '2027-07-10T20:59:59.999999Z' }; promos.push(data) }
        else { data = { ...promos[0], ...lastBody }; promos[0] = data }
      } else if (path.endsWith('/promos')) data = promos
      else if (path.includes('notifications')) data = { items: [], unread: 0 }
      else if (path.includes('badges')) data = { orders_new: 0, support_unread: 0 }
      else if (path.includes('statuses')) data = { statuses: [] }
      await route.fulfill({ json: data })
    })
    await page.goto('http://127.0.0.1:5173/promos')
    await page.getByRole('button', { name: /Створити промокод/ }).click()
    const dialog = page.getByRole('dialog')
    let save = dialog.getByRole('button', { name: 'Створити промокод', exact: true })
    check(await save.isDisabled(), `${width}: empty form cannot save`)
    await dialog.getByLabel('Промокод', { exact: true }).fill('welcome')
    await dialog.getByLabel('Розмір знижки', { exact: true }).fill('101')
    check(await save.isDisabled() && await dialog.getByText('Відсоткова знижка не може перевищувати 100%.', { exact: true }).isVisible(), `${width}: invalid percent visibly rejected`)
    await dialog.getByRole('radio', { name: /Фіксована сума/ }).check()
    check(await save.isEnabled(), `${width}: fixed discount above 100 allowed`)
    await dialog.getByRole('radio', { name: /Відсоток/ }).check()
    await dialog.getByLabel('Розмір знижки', { exact: true }).fill('10.25')
    await dialog.getByLabel('На одного клієнта', { exact: true }).fill('')
    check(await save.isDisabled(), `${width}: empty customer limit rejected`)
    await dialog.getByLabel('На одного клієнта', { exact: true }).fill('1')
    await dialog.getByRole('radio', { name: 'Обрані категорії', exact: true }).check()
    check(await save.isDisabled(), `${width}: empty category selection cannot become unrestricted`)
    if (categoryFail) {
      await dialog.getByText('Категорії тимчасово недоступні', { exact: true }).waitFor()
      check(await save.isDisabled(), `${width}: category fetch failure blocks scoped save`)
      categoryFail = false
      await dialog.getByRole('button', { name: 'Завантажити категорії повторно' }).click()
    }
    await dialog.getByLabel('Пошук категорій').fill('Рідини')
    await dialog.getByRole('checkbox', { name: /Рідини/ }).check()
    await dialog.getByLabel('Пошук категорій').fill('Пристрої')
    await dialog.getByRole('button', { name: 'Вибрати знайдені', exact: true }).click()
    check(await dialog.getByRole('button', { name: /Прибрати категорію Рідини/ }).count() === 1 && await dialog.getByRole('checkbox', { name: /Пристрої/ }).isChecked(), `${width}: category search retains selections`)
    await dialog.getByRole('button', { name: 'Очистити', exact: true }).click()
    check(await save.isDisabled(), `${width}: clearing categories blocks save`)
    await dialog.getByLabel('Пошук категорій').fill('Рідини')
    await dialog.getByRole('checkbox', { name: /Рідини/ }).check()
    await dialog.getByLabel('Діє до', { exact: true }).fill('2027-07-10')
    await dialog.getByRole('button', { name: 'Згенерувати', exact: true }).click()
    check(/^ELFAR[A-Z2-9]{6}$/.test(await dialog.getByLabel('Промокод', { exact: true }).inputValue()), `${width}: code generator creates usable code`)
    await dialog.getByLabel('Промокод', { exact: true }).fill('welcome')
    check(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth) && await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}: no horizontal overflow`)
    check(await save.isVisible(), `${width}: save remains visible while form scrolls`)
    await save.click()
    await dialog.getByText('Промокод із таким кодом уже існує', { exact: true }).waitFor()
    check(await dialog.getByLabel('Розмір знижки').inputValue() === '10.25' && await dialog.getByRole('checkbox', { name: /Рідини/ }).isChecked(), `${width}: error preserves inputs and scope`)
    await save.evaluate((button) => { button.form.requestSubmit(); button.form.requestSubmit() })
    await dialog.getByRole('button', { name: 'Зберігаємо…', exact: true }).waitFor()
    check(writes === 2 && await dialog.getByLabel('Промокод', { exact: true }).isDisabled(), `${width}: double submit locked`)
    await page.keyboard.press('Escape')
    check(await dialog.isVisible(), `${width}: pending write keeps dialog open`)
    while (!release) await page.waitForTimeout(20)
    check(lastBody.code === 'WELCOME' && lastBody.value === '10.25' && lastBody.category_ids.join() === '1', `${width}: normalized code, exact amount and scope submitted`)
    check(lastBody.expires_on === '2027-07-10' && lastBody.max_uses === null && lastBody.per_user_limit === 1, `${width}: timezone-independent date and limits`)
    release(); release = null
    await dialog.waitFor({ state: 'hidden' })
    await page.getByRole('button', { name: 'Редагувати', exact: true }).click()
    check(await dialog.getByLabel('Діє до', { exact: true }).inputValue() === '2027-07-10' && await dialog.getByRole('checkbox', { name: /Рідини/ }).isChecked(), `${width}: editing restores Kyiv date and scope`)
    await dialog.screenshot({ path: `qa/output/promo-code-${width}.png` })
    await dialog.getByLabel('Розмір знижки', { exact: true }).press('Enter')
    await dialog.getByRole('button', { name: 'Зберігаємо…', exact: true }).waitFor()
    while (!release) await page.waitForTimeout(20)
    check(lastBody.expires_at === '2027-07-10T20:59:59.999999Z' && !('expires_on' in lastBody), `${width}: unchanged expiry keeps exact instant`)
    release(); release = null
    await dialog.waitFor({ state: 'hidden' })
    await page.getByLabel('Пошук промокодів').fill('Рідини')
    check(await page.locator('.promo-card').count() === 1, `${width}: category search finds promotion`)
    await page.getByLabel('Статус промокодів').selectOption('inactive')
    await page.getByText('Промокодів за цими умовами немає', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Скинути пошук і фільтр' }).click()
    await page.getByRole('button', { name: 'Дублювати', exact: true }).click()
    check(!(await dialog.getByRole('checkbox', { name: /Промокод активний/ }).isChecked()) && (await dialog.getByLabel('Промокод', { exact: true }).inputValue()).endsWith('-COPY'), `${width}: duplicate starts disabled with a new code`)
    await dialog.getByRole('button', { name: 'Скасувати', exact: true }).click()
    await page.screenshot({ path: `qa/output/promo-page-${width}.png`, fullPage: true })
    check(errors.length === 0, `${width}: no React errors ${errors.join('; ')}`)
    await page.close()
  }
  console.log(`Promo browser: ${checks} checks passed`)
} finally { await browser.close() }
