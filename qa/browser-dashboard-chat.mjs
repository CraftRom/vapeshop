import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true,
  executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || undefined, args: ['--no-sandbox'] })
const base = process.env.DASHBOARD_URL || 'http://127.0.0.1:5173'
let checks = 0
const check = (ok, label) => { assert.ok(ok, label); checks++; console.log('PASS ' + label) }
const pause = ms => new Promise(resolve => setTimeout(resolve, ms))
const message = (id, text = `Репліка ${id} — тестова історія переписки`) => ({
  id, text, direction: id % 2 ? 'in' : 'out', is_read: true, delivered: true,
  created_at: '2026-10-15T07:00:00Z', author: 'QA',
})
const order = id => ({ id, status: 'accepted', can_chat: true, total: '19.90', subtotal: '19.90',
  discount: '0', bonus_used: '0', items: [], payment_method: 'card', created_at: '2026-10-15T07:00:00Z',
  contact_name: 'QA', user: { tg_id: 123 }, tracking_number: '', admin_note: '' })
const thread = id => ({ id, user_id: id, status: 'open', unread_count: 0,
  user: { first_name: `Клієнт ${id}`, tg_id: id }, created_at: '2026-10-15T07:00:00Z' })

async function bottom(log) { return log.evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight < 3) }
async function anchor(log) {
  return log.evaluate(el => {
    const top = el.getBoundingClientRect().top
    const item = [...el.querySelectorAll('[data-message-id]')].find(node => node.getBoundingClientRect().bottom > top)
    return { id: item?.dataset.messageId, offset: item ? item.getBoundingClientRect().top - top : 0 }
  })
}
async function anchorStayed(log, before, label) {
  const after = await log.evaluate((el, id) => {
    const item = el.querySelector(`[data-message-id="${id}"]`)
    return { id: item?.dataset.messageId, offset: item ? item.getBoundingClientRect().top - el.getBoundingClientRect().top : 0 }
  }, before.id)
  check(after.id === before.id && Math.abs(after.offset - before.offset) < 3,
    `${label}: same visible reply and offset (${JSON.stringify(before)} -> ${JSON.stringify(after)})`)
}
async function wake(page) { await page.evaluate(() => window.dispatchEvent(new Event('focus'))); await pause(200) }

try {
  for (const width of (process.env.QA_CHAT_WIDTH ? [Number(process.env.QA_CHAT_WIDTH)] : [1280, 390, 320])) {
    const page = await browser.newPage({ viewport: { width, height: 820 }, isMobile: width < 760, hasTouch: width < 760 })
    const errors = []; page.on('pageerror', error => errors.push(error.message))
    const data = { order: Array.from({ length: 300 }, (_, i) => message(i + 1)),
      1: Array.from({ length: 80 }, (_, i) => message(i + 1)),
      2: [message(1001, 'Лише другий чат')], fail: false, hold: null, sendHold: null, calls: [], posts: [] }
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url()), path = url.pathname, q = url.searchParams
      const method = route.request().method(); data.calls.push([path, q.toString()])
      let json = {}
      if (path === '/api/auth/session') json = { role: 'admin', name: 'QA', csrf_token: 'qa' }
      else if (/^\/api\/orders\/\d+$/.test(path)) json = order(Number(path.split('/').at(-1)))
      else if (path.endsWith('/messages/read')) json = { marked: 0 }
      else if (/\/(orders|support)\/\d+\/messages$/.test(path)) {
        const support = path.includes('/support/'), id = Number(path.split('/').at(-2))
        const items = support ? data[id] : data.order
        if (method === 'POST') {
          if (data.sendFail) { await route.fulfill({status:503,json:{detail:'Тестова відмова надсилання'}}); return }
          data.posts.push(route.request().postDataJSON().text)
          if (data.sendHold) await data.sendHold
          if (data.raceReplies) { const baseId = items.at(-1).id; for (let i=1;i<=400;i++) items.push(message(baseId+i, `Конкурентна репліка ${i}`)); data.raceReplies=false }
          const sent = { ...message(Number(items.at(-1)?.id || 0) + 1, route.request().postDataJSON().text), direction: 'out' }
          items.push(sent); json = { message: sent, delivered: true }
        } else {
          const snapshot = structuredClone(items)
          if (data.hold && (!support || id === 1)) await data.hold
          if (data.fail) { await route.fulfill({ status: 503, json: { detail: 'Тестовий збій переписки' } }); return }
          json = q.has('before_id') ? snapshot.filter(m => m.id < Number(q.get('before_id'))).slice(-200)
            : q.has('after_id') ? snapshot.filter(m => m.id > Number(q.get('after_id'))).slice(0, 200) : snapshot.slice(-200)
        }
      } else if (path === '/api/support') json = [thread(1), thread(2)]
      else if (path === '/api/support/stats') json = { open: 2, closed: 0, total: 2, clients: 2, unread: 0 }
      else if (/^\/api\/support\/\d+$/.test(path)) json = thread(Number(path.split('/').at(-1)))
      else if (path.includes('salesdrive-statuses')) json = { statuses: [] }
      else if (path.includes('badges')) json = { orders_new: 0, support_unread: 0 }
      else if (path.includes('notifications')) json = { items: [], unread: 0 }
      await route.fulfill({ json })
    })

    for (const kind of ['order', 'support']) {
      const support = kind === 'support'
      await page.goto(base + (support ? '/support?thread=1' : '/orders/7#chat'))
      const log = page.getByRole('region', { name: support ? 'Переписка підтримки' : 'Переписка замовлення', exact: true })
      const card = support ? page.locator('.support-conversation') : page.locator('.order-chat-card')
      const compose = card.locator('textarea')
      await log.locator('[data-message-id]').last().waitFor()
      await pause(200)
      const label = `${width}/${kind}`
      check(await log.evaluate(el => el.scrollHeight > el.clientHeight && el.clientHeight > 100), label + ': bounded internal scroll')
      check(await bottom(log), label + ': opens at newest reply')
      await compose.fill('Чернетка для ' + label)
      await pause(400) // Let the browser finish its focus/hash scroll before measuring polling.
      await card.evaluate(el => { window.__chatCard = el; window.__chatInput = el.querySelector('textarea') })
      const pageY = await page.evaluate(() => scrollY)
      const startCalls = data.calls.length
      await wake(page)
      check(await bottom(log), label + ': unchanged poll keeps newest reply visible')
      const pageAfter = await page.evaluate(() => scrollY)
      check(Math.abs(pageAfter - pageY) < 2, label + `: polling does not scroll page (${pageY} -> ${pageAfter})`)
      check(await card.evaluate(el => el === window.__chatCard && el.querySelector('textarea') === window.__chatInput), label + ': card and composer remain mounted')
      check(await compose.inputValue() === 'Чернетка для ' + label, label + ': draft survives polling')
      check(await compose.evaluate(el => el === document.activeElement), label + ': typing focus survives polling')
      check(data.calls.slice(startCalls).some(([p]) => p.endsWith('/messages')), label + ': chat fetches independently in background')

      const list = support ? data[1] : data.order
      const added = message(list.at(-1).id + 1, 'Нове повідомлення внизу')
      list.push(added)
      try { await log.locator(`[data-message-id="${added.id}"]`).waitFor({ timeout: 20000 }) }
      catch (error) { console.log('TIMER DEBUG', label, await page.evaluate(() => ({hidden:document.hidden,online:navigator.onLine})), data.calls.slice(-15)); throw error }
      check(await bottom(log), label + ': background timer follows appended reply while already at bottom')

      await log.evaluate(el => { el.scrollTop = Math.floor(el.scrollHeight / 3) }); await pause(80)
      const old = await anchor(log)
      const second = message(list.at(-1).id + 1, 'Нове повідомлення під час читання історії')
      list.push(second); await wake(page)
      await log.locator(`[data-message-id="${second.id}"]`).waitFor()
      await anchorStayed(log, old, label + ': appended message')
      const latest = card.getByRole('button', { name: /Нові повідомлення:/ })
      check(await latest.isVisible(), label + ': explicit new-message jump appears')

      data.fail = true; await wake(page)
      await card.getByText('Не вдалося оновити переписку.', { exact: true }).waitFor()
      await anchorStayed(log, old, label + ': network failure')
      check(await compose.inputValue() === 'Чернетка для ' + label, label + ': failure retains draft')
      data.fail = false
      // Programmatic click avoids Playwright scrolling a long order page for this assertion.
      await card.getByRole('button', { name: 'Оновити чат', exact: true }).evaluate(el => el.click()); await pause(200)
      await anchorStayed(log, old, label + ': retry')
      await latest.evaluate(el => el.click()); await pause(80)
      check(await bottom(log), label + ': explicit jump reaches newest reply')

      await page.setViewportSize({ width, height: 620 }); await pause(120)
      check(await bottom(log), label + ': shrinking viewport keeps newest reply')
      if (support) check(await compose.evaluate(el => el.getBoundingClientRect().bottom <= window.innerHeight), label + ': mobile/desktop composer fits reduced viewport')
      await page.setViewportSize({ width, height: 820 }); await pause(100)

      if (!support) {
        await log.evaluate(el => { el.scrollTop = 0 }); await pause(60)
        const before = await anchor(log)
        let release; data.hold = new Promise(resolve => { release = resolve })
        await card.getByRole('button', { name: 'Показати попередні повідомлення', exact: true }).evaluate(el => el.click())
        await pause(50)
        const incoming = message(list.at(-1).id + 1, 'Поки завантажується стара історія')
        list.push(incoming); data.hold = null; await wake(page)
        release(); await log.locator('[data-message-id="1"]').waitFor()
        await log.locator(`[data-message-id="${incoming.id}"]`).waitFor()
        await anchorStayed(log, before, label + ': prepend during live append')
        check(await log.locator('[data-message-id]').count() === list.length, label + ': older history and concurrent reply both retained')

        // A late attachment above the visible anchor changes heights without new messages.
        const mediaAnchor = await anchor(log)
        await log.locator('[data-message-id="1"]').evaluate(el => {
          const image = document.createElement('img'); image.alt = 'QA'; image.style.cssText = 'display:block;width:100%;height:160px'
          el.append(image)
        }); await pause(120)
        await anchorStayed(log, mediaAnchor, label + ': delayed attachment layout')

        const oldLast = list.at(-1).id
        for (let i = 1; i <= 450; i++) list.push(message(oldLast + i, `Пакет ${i}`))
        await wake(page); await log.locator(`[data-message-id="${oldLast + 450}"]`).waitFor()
        check(await log.locator('[data-message-id]').count() === list.length, label + ': catches >200 incoming replies without gaps')
      }

      await compose.fill('Надсилаю ' + label)
      let releaseSend; data.sendHold = new Promise(resolve => { releaseSend = resolve })
      await card.getByRole('button', { name: 'Надіслати', exact: true }).evaluate(el => { el.click(); el.click() })
      await pause(50); await compose.fill('Наступна чернетка ' + label)
      const countPosts = data.posts.length
      if (!support) data.raceReplies = true
      releaseSend(); data.sendHold = null
      await card.getByRole('button', { name: 'Надіслати', exact: true }).waitFor()
      await pause(150)
      check(data.posts.length === countPosts, label + ': double click sends once')
      check(await compose.inputValue() === 'Наступна чернетка ' + label, label + ': send completion retains subsequently typed text')
      check(await bottom(log), label + ': own send returns to newest reply')
      if (!support) {
        await wake(page)
        await page.waitForFunction(expected => document.querySelectorAll('.chat-log [data-message-id]').length === expected, list.length)
        check(await log.locator('[data-message-id]').count() === list.length, label + ': own POST never skips preceding client replies')
      }

      data.sendFail = true
      await compose.fill('Невдала відповідь ' + label)
      const beforeFailure = await log.locator('[data-message-id]').count()
      await card.getByRole('button', { name: 'Надіслати', exact: true }).evaluate(el => el.click())
      await page.getByText('Тестова відмова надсилання', { exact: true }).waitFor()
      check(await compose.inputValue() === 'Невдала відповідь ' + label, label + ': failed send keeps complete draft')
      check(await log.locator('[data-message-id]').count() === beforeFailure, label + ': failed send does not invent a message')
      data.sendFail = false
      await compose.fill('Наступна чернетка ' + label)

      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), label + ': no horizontal page overflow')
      if (process.env.QA_CAPTURE_DIR) {
        mkdirSync(process.env.QA_CAPTURE_DIR, { recursive: true })
        await page.screenshot({ path: `${process.env.QA_CAPTURE_DIR}/chat7-${kind}-${width}.png` })
      }
    }

    // Switch while an old conversation request is still waiting.
    let releaseOld; data.hold = new Promise(resolve => { releaseOld = resolve })
    await wake(page)
    const back = page.getByRole('button', { name: '← Назад', exact: true })
    if (width < 760) await back.click()
    await page.locator('.support-session').filter({ hasText: '#2' }).click()
    const supportLog = page.getByRole('region', { name: 'Переписка підтримки', exact: true })
    await supportLog.locator('[data-message-id="1001"]').waitFor()
    data.hold = null; releaseOld(); await pause(180)
    check(await supportLog.locator('[data-message-id]').count() === 1, width + ': old response cannot contaminate new conversation')
    check(await page.locator('.support-compose textarea').inputValue() === '', width + ': another customer never inherits draft')
    if (width < 760) await back.click()
    await page.locator('.support-session').filter({ hasText: '#1' }).click()
    await page.locator('.support-compose textarea').waitFor()
    check(await page.locator('.support-compose textarea').inputValue() === 'Наступна чернетка ' + width + '/support', width + ': own draft restored after switching back')
    check(errors.length === 0, width + ': no React errors: ' + errors.join('; '))
    await page.close()
  }
} finally { await browser.close() }
console.log(`DASHBOARD CHAT BROWSER: ${checks}/${checks}`)
