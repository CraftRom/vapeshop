// UI-011: dashboard support on a phone. Emulated iPhone 13 and Pixel 7 (touch,
// mobile viewport): inbox → conversation → back, three conversations with
// their own drafts, the on-screen keyboard (viewport shrinks), Enter on a
// touch keyboard, and the shared accessibility audit with axe-core.
import assert from 'node:assert/strict'
import { chromium, devices } from 'playwright'
import { auditAxe, auditPage } from './a11y-audit.mjs'

const BASE = process.env.DASHBOARD_URL || 'http://127.0.0.1:5173'
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || undefined, args: ['--no-sandbox'] })
let checks = 0
const failures = []
const check = (ok, label) => { checks++; console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`); if (!ok) failures.push(label) }
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const thread = (id, name) => ({ id, user_id: id, status: 'open', unread_count: id === 1 ? 2 : 0, last_message_at: '2026-11-19T10:00:00Z', created_at: '2026-11-18T08:00:00Z', user: { first_name: name, tg_id: 100 + id, username: 'client' + id, phone: '+38067000000' + id } })
const THREADS = [thread(1, 'Олена'), thread(2, 'Тарас'), thread(3, 'Ірина')]
const messages = (id) => Array.from({ length: 30 }, (_, i) => ({ id: id * 1000 + i, thread_id: id, user_id: id, direction: i % 3 ? 'in' : 'out', is_read: true, author: 'QA', text: `Звернення ${id}, повідомлення ${i + 1}. Чи є в наявності Aventus 5 мл?`, created_at: '2026-11-19T09:00:00Z' }))

try {
  for (const name of ['iPhone 13', 'Pixel 7']) {
    const context = await browser.newContext({ ...devices[name] })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    const sent = []
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url()), path = url.pathname, method = route.request().method()
      let json = {}
      if (path === '/api/auth/session') json = { role: 'admin', name: 'QA', csrf_token: 'qa', operator_id: 1, draft_scope: 'support-mobile-' + name }
      else if (path === '/api/support') json = THREADS
      else if (path === '/api/support/stats') json = { open: 3, closed: 0, total: 3, clients: 3, unread: 2 }
      else if (/^\/api\/support\/\d+$/.test(path)) json = THREADS.find((t) => t.id === Number(path.split('/').pop()))
      else if (/^\/api\/support\/\d+\/messages$/.test(path) && method === 'POST') { sent.push(route.request().postDataJSON().text); json = { id: 9999, direction: 'out', text: sent.at(-1), created_at: new Date().toISOString(), is_read: true } }
      else if (/^\/api\/support\/\d+\/messages$/.test(path)) json = url.searchParams.has('after_id') || url.searchParams.has('before_id') ? [] : messages(Number(path.split('/').at(-2)))
      else if (path.endsWith('/messages/read')) json = { marked: 0 }
      else if (path.includes('badges')) json = { orders_new: 0, support_unread: 2 }
      else if (path.includes('notifications')) json = { items: [], unread: 0 }
      await route.fulfill({ json })
    })
    const cdp = await context.newCDPSession(page)

    await page.goto(BASE + '/support')
    await page.locator('h1').first().waitFor()
    await page.getByText('Олена').first().waitFor()
    await page.waitForLoadState('networkidle')
    const first = await page.getByText('Звернення #1').first().boundingBox()
    check(first && first.y + first.height <= page.viewportSize().height, `${name}: the first conversation is on the first screen (${Math.round(first?.y)}px)`)
    check(await page.getByRole('button', { name: /^В роботі\s*3$/ }).count() === 1, `${name}: the filter buttons carry the counts`)
    await auditPage(page, cdp, `${name} inbox`, check, { errors })
    await auditAxe(page, `${name} inbox`, check)

    // Open the first conversation with a tap.
    await page.getByText('Звернення #1').first().tap()
    const log = page.getByRole('region', { name: 'Переписка підтримки', exact: true })
    await log.locator('[data-message-id="1029"]').waitFor()
    await pause(150)
    check(new URL(page.url()).searchParams.get('thread') === '1', `${name}: the conversation has its own address`)
    const inboxHidden = await page.locator('.support-inbox').evaluate((el) => getComputedStyle(el).display === 'none' || el.getBoundingClientRect().width === 0)
    check(inboxHidden, `${name}: the conversation takes the whole screen`)
    const composer = page.getByRole('textbox', { name: 'Відповідь клієнту' })
    const box = await composer.boundingBox()
    const view = page.viewportSize()
    check(Boolean(box) && box.y + box.height <= view.height && box.y >= 0, `${name}: the reply field is on screen without scrolling the page`)
    check(await composer.evaluate((el) => parseFloat(getComputedStyle(el).fontSize) >= 16), `${name}: the reply field is 16 px, so focusing it does not zoom`)
    const send = page.getByRole('button', { name: 'Надіслати' })
    const sendBox = await send.boundingBox()
    check(sendBox.height >= 44 && sendBox.width >= 44, `${name}: the send button is a 44 px touch target (${Math.round(sendBox.width)}×${Math.round(sendBox.height)})`)
    check(await log.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight < 8), `${name}: opens at the latest message`)
    await auditPage(page, cdp, `${name} conversation`, check, { errors })
    await auditAxe(page, `${name} conversation`, check)

    // Enter on a touch keyboard starts a new line; sending is the button.
    await composer.tap()
    await composer.type('Так, є')
    await composer.press('Enter')
    await composer.type('Відправимо сьогодні')
    check(sent.length === 0 && (await composer.inputValue()) === 'Так, є\nВідправимо сьогодні', `${name}: Enter on the phone keyboard adds a line instead of sending`)
    check(await page.getByText('Shift+Enter').count() === 0, `${name}: no Shift+Enter hint on a phone`)

    // On-screen keyboard: the visual viewport loses ~45% of its height.
    await page.setViewportSize({ width: view.width, height: Math.round(view.height * 0.55) })
    await pause(250)
    const small = await composer.boundingBox()
    check(small.y + small.height <= Math.round(view.height * 0.55) + 1, `${name}: the reply field stays above the keyboard`)
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${name}: no sideways scroll with the keyboard open`)
    await page.setViewportSize(view)
    await pause(150)

    // The phone's own Back gesture returns to the list, not out of the page.
    await page.goBack()
    await page.getByText('Звернення #2').first().waitFor()
    check(new URL(page.url()).pathname === '/support' && !new URL(page.url()).searchParams.has('thread') && await page.locator('.support-inbox').isVisible(), `${name}: system Back returns to the list`)
    await page.goForward()
    await log.locator('[data-message-id="1029"]').waitFor()
    check((await composer.inputValue()) === 'Так, є\nВідправимо сьогодні', `${name}: Forward reopens the conversation with its draft`)

    // Back to the list, open two more conversations: each keeps its draft.
    await page.getByRole('button', { name: '← Назад' }).tap()
    await page.getByText('Тарас').first().waitFor()
    check(await page.locator('.support-inbox').isVisible(), `${name}: Back returns to the list`)
    await page.getByText('Звернення #2').first().tap()
    await log.locator('[data-message-id="2029"]').waitFor()
    check((await composer.inputValue()) === '', `${name}: another conversation starts with an empty reply`)
    await composer.fill('Чернетка для Тараса')
    await page.getByRole('button', { name: '← Назад' }).tap()
    await page.getByText('Звернення #3').first().tap()
    await log.locator('[data-message-id="3029"]').waitFor()
    await page.getByRole('button', { name: '← Назад' }).tap()
    await page.getByText('Звернення #1').first().tap()
    await log.locator('[data-message-id="1029"]').waitFor()
    await pause(100)
    check((await composer.inputValue()) === 'Так, є\nВідправимо сьогодні', `${name}: the first conversation keeps its draft`)
    await send.tap()
    await pause(200)
    check(sent.at(-1) === 'Так, є\nВідправимо сьогодні', `${name}: the button sends the whole multi-line reply`)
    check(errors.length === 0, `${name}: no runtime errors ${errors.join('; ')}`)
    if (process.env.QA_CAPTURE_DIR) await page.screenshot({ path: `${process.env.QA_CAPTURE_DIR}/support-mobile-${name.replace(/\W+/g, '-')}.png` })
    await context.close()
  }
} finally { await browser.close() }
console.log(`SUPPORT MOBILE: ${checks - failures.length}/${checks}`)
if (failures.length) process.exitCode = 1
