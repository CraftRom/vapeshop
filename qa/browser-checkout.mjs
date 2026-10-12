import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH, args: ['--no-sandbox'] } : {}) })
let checks = 0
const check = (condition, label) => { assert.ok(condition, label); checks++; console.log(`PASS ${label}`) }
const tokens = ['a'.repeat(64), 'b'.repeat(64), 'c'.repeat(64)]

async function setup(width = 390) {
  const context = await browser.newContext({ viewport: { width, height: 820 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  const state = { quoteFail: false, checkoutMode: 'success', checkoutCalls: [], quoteCalls: [], updated: false, committed: false, slowOld: false, delays: false, alert: '' }
  await page.addInitScript(() => {
    window.Telegram = { WebApp: { initData: 'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test', platform: 'tdesktop', initDataUnsafe: { user: { id: 123 } }, ready() {}, expand() {}, disableVerticalSwipes() {}, onEvent() {}, offEvent() {}, close() {}, showAlert(text, callback) { window.__checkoutAlert = text; callback?.() } } }
  })
  await page.route('https://telegram.org/**', (route) => route.fulfill({ body: '' }))
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    let data = []
    if (path.endsWith('/config')) data = { age_confirmed: true, currency: 'грн', bonus_enabled: true, bonus_max_percent: '30', volume_discount_enabled: true, volume_discount_min: '100', volume_discount_percent: '10', referral_enabled: false }
    else if (path.endsWith('/checkout/quote')) {
      const body = route.request().postDataJSON()
      state.quoteCalls.push(body)
      if (state.quoteFail || state.committed) { await route.fulfill({ status: 400, json: { detail: state.committed ? 'Кошик порожній' : 'Не вдалося розрахувати суму' } }); return }
      const updated = state.updated
      data = body.promo_code === 'P20'
        ? { subtotal: '199.90', discount: '39.98', discount_source: 'promo', bonus_available: '47.98', bonus_used: body.use_bonus ? '47.98' : '0.00', total: body.use_bonus ? '111.94' : '159.92', quote_token: tokens[2] }
        : { subtotal: updated ? '209.90' : '199.90', discount: updated ? '20.99' : '19.99', discount_source: 'volume', bonus_available: '53.97', bonus_used: body.use_bonus ? '53.97' : '0.00', total: updated ? '188.91' : body.use_bonus ? '125.94' : '179.91', quote_token: updated ? tokens[1] : tokens[0] }
      if (state.delays) await new Promise((resolve) => setTimeout(resolve, body.use_bonus ? 30 : 650))
    } else if (path.endsWith('/checkout') && method === 'POST') {
      const payload = route.request().postDataJSON()
      state.checkoutCalls.push(payload)
      if (state.checkoutMode === 'changed' && state.checkoutCalls.length === 1) {
        state.updated = true
        await route.fulfill({ status: 409, json: { detail: 'Кошик або сума змінилися. Перевірте оновлений підсумок і підтвердьте ще раз' } }); return
      }
      if (state.checkoutMode === 'lost' && state.checkoutCalls.length === 1) {
        state.committed = true
        await route.abort('failed'); return
      }
      data = { order_id: 42, total: state.updated ? '188.91' : '179.91', payment_method: 'card' }
    } else if (path.endsWith('/promo/check')) data = { ok: true, discount: '39.98' }
    else if (path.endsWith('/cart')) data = { lines: [{ product_id: 1, name: 'Товар', qty: 1, price: '199.90', stock: 10, line_total: '199.90' }], subtotal: '199.90' }
    else if (path.endsWith('/profile')) data = { first_name: 'Дмитро', phone: '+380671234567', bonus_balance: '100.00', max_bonus_now: '59.97', orders_count: 0 }
    else if (path.endsWith('/categories')) data = [{ id: 1, name: 'Товари' }]
    else if (path.endsWith('/products')) data = [{ id: 1, category_id: 1, name: 'Товар', price: '199.90', stock: 10 }]
    await route.fulfill({ json: data })
  })
  await page.goto((process.env.MINIAPP_URL || 'http://127.0.0.1:5174') + '/app/')
  await page.getByRole('button', { name: 'Оформити', exact: true }).click()
  await page.getByRole('heading', { name: 'Оформлення', exact: true }).waitFor()
  await page.locator('#surname').fill('Тест')
  await page.locator('#city').fill('Київ')
  await page.locator('#address').fill('Відділення 1')
  return { page, context, state, errors }
}

try {
  for (const width of [320, 390, 1280]) {
    const { page, context, state, errors } = await setup(width)
    await page.locator('.summary .total').getByText('179,91 грн', { exact: true }).waitFor()
    check(await page.locator('.summary').getByText('19,99 грн', { exact: false }).count() > 0, `${width}px автоматична знижка із сервера`)
    check((await page.getByText(/доступно/).innerText()).includes('53,97'), `${width}px бонусний ліміт після знижки`)
    await page.getByRole('checkbox').check()
    await page.locator('.summary .total').getByText('125,94 грн', { exact: true }).waitFor()
    check(state.quoteCalls.some((input) => input.use_bonus), `${width}px бонуси розраховує сервер`)
    await page.getByRole('checkbox').uncheck()
    await page.locator('.summary .total').getByText('179,91 грн', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Підтвердити замовлення', exact: true }).dblclick()
    await page.waitForFunction(() => window.__checkoutAlert?.includes('179,91'))
    check(state.checkoutCalls.length === 1 && state.checkoutCalls[0].quote_token === tokens[0], `${width}px double click надсилає один POST з показаним підсумком`)
    check((await page.evaluate(() => window.__checkoutAlert)).includes('179,91 грн'), `${width}px успіх з точною сумою`)
    check(!errors.length, `${width}px без помилок React`)
    await context.close()
  }
  {
    const { page, context, state } = await setup()
    await page.locator('.summary .total').getByText('179,91 грн', { exact: true }).waitFor()
    state.delays = true
    // Trigger two quotes, with the older response arriving last.
    await page.getByRole('checkbox').check()
    await page.getByRole('checkbox').uncheck()
    await page.getByRole('checkbox').check()
    await page.locator('.summary .total').getByText('125,94 грн', { exact: true }).waitFor()
    await page.waitForTimeout(750)
    check((await page.locator('.summary .total').innerText()).includes('125,94'), 'стара відповідь quote не перезаписує новий вибір бонусів')
    await page.locator('#promo').fill('P20')
    await page.getByRole('button', { name: 'Застосувати', exact: true }).click()
    await page.locator('.summary .total').getByText('111,94 грн', { exact: true }).waitFor()
    check((await page.locator('.summary').innerText()).includes('39,98'), 'перемагає промокод; бонуси перераховані після нього')
    await context.close()
  }
  {
    const { page, context, state } = await setup()
    await page.locator('.summary .total').getByText('179,91 грн', { exact: true }).waitFor()
    state.quoteFail = true
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: 'Повторити розрахунок', exact: true }).waitFor()
    check(await page.getByRole('button', { name: 'Підтвердити замовлення', exact: true }).isDisabled(), 'збій quote показаний і не дозволяє оформлення за старою сумою')
    state.quoteFail = false
    await page.getByRole('button', { name: 'Повторити розрахунок', exact: true }).click()
    await page.locator('.summary .total').getByText('125,94 грн', { exact: true }).waitFor()
    check(await page.getByRole('button', { name: 'Підтвердити замовлення', exact: true }).isEnabled(), 'повтор quote відновлює оформлення')
    await context.close()
  }
  {
    const { page, context, state } = await setup()
    state.checkoutMode = 'changed'
    await page.getByRole('button', { name: 'Підтвердити замовлення', exact: true }).click()
    await page.locator('.summary .total').getByText('188,91 грн', { exact: true }).waitFor()
    check(state.checkoutCalls.length === 1, '409 оновлює суму без автоматичної покупки')
    check(await page.locator('#surname').inputValue() === 'Тест', 'зміна підсумку зберігає контактні поля')
    await page.getByRole('button', { name: 'Підтвердити замовлення', exact: true }).click()
    await page.waitForFunction(() => window.__checkoutAlert?.includes('188,91'))
    check(state.checkoutCalls[1].quote_token === tokens[1] && state.checkoutCalls[0].checkout_key === state.checkoutCalls[1].checkout_key, 'повторне підтвердження використовує новий підсумок і той самий ключ')
    await context.close()
  }
  {
    const { page, context, state } = await setup()
    state.checkoutMode = 'lost'
    await page.getByRole('button', { name: 'Підтвердити замовлення', exact: true }).click()
    await page.getByRole('button', { name: 'Перевірити замовлення', exact: true }).waitFor()
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: 'Повторити розрахунок', exact: true }).waitFor()
    await page.locator('#surname').fill('')
    check(await page.getByRole('button', { name: 'Перевірити замовлення', exact: true }).isEnabled(), 'після втрати відповіді повтор доступний навіть із порожнім серверним кошиком')
    await page.getByRole('button', { name: 'Перевірити замовлення', exact: true }).click()
    await page.waitForFunction(() => window.__checkoutAlert?.includes('179,91'))
    check(JSON.stringify(state.checkoutCalls[0]) === JSON.stringify(state.checkoutCalls[1]), 'невідомий результат перевіряється повтором незмінного payload і ключа')
    await context.close()
  }
} finally { await browser.close() }
console.log(`BROWSER CHECKOUT: ${checks}/${checks}`)
