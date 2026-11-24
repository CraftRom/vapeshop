import {readSourceCss} from './helpers/source-css.mjs'
import fs from 'node:fs'
import assert from 'node:assert/strict'

const read = path => fs.readFileSync(path, 'utf8')
const page = read('src/pages/Support.jsx')
const app = read('src/App.jsx')
const api = read('src/api.js')
const css = readSourceCss()
const live = read('src/components/RealtimeOrders.jsx')
const notification = read('src/components/NotificationCenter.jsx')
const messages = read('src/components/useChatMessages.js')
const layout = read('src/components/useSupportLayoutSize.js')
const source = read('../backend/shop/services/realtime.py')
const router = read('../backend/api/routers/realtime.py')
const support = read('../backend/api/routers/support.py')
const shop = read('../backend/api/routers/shop_support.py')
const bot = read('../backend/shop/services/support_chat.py')
let passed = 0
function check(label, test) {
  assert.ok(test, label)
  console.log(`✓ ${label}`)
  passed++
}

// Route isolation: only the selected chat is rendered, with normal cookie auth.
check('standalone chat has an independent protected route', app.includes('path="/support/chat/:id"') && app.includes('<ProtectedChatWindow>'))
check('pop-out does not render dashboard Shell', app.includes('return getToken() ? <PageBoundary>') && app.includes('return getToken() ? <Shell>'))
check('standalone reuses the same Conversation (including files, close and send)', page.includes('function SupportChatWindow()') && page.includes('<Conversation key={threadId}') && page.includes('onDelete={leave}'))
check('thread identity is strictly a positive integer', page.includes('Number.isSafeInteger(threadId)') && page.includes('threadId <= 2147483647'))
check('different chats get different named browser windows', page.includes('`elfar-support-${thread.id}`') && page.includes('resizable=yes'))
check('pop-out drops opener reference', page.includes('popup.opener = null') && page.includes('window.opener = null'))
check('pop-out has no inbox and owns exactly one thread', page.includes('className="support-popout-page"') && page.includes('standalone onBack={leave}'))
check('pop-out preserves audio notification leader without extra bell', page.includes('<NotificationCenter headless />') && notification.includes('if (headless) return null'))
check('audio leadership moves to focused window', notification.includes("window.addEventListener('focus', onFocus)") && notification.includes('document.hidden) { release()'))

check('list content alone scrolls and groups never clip sessions', css.includes('.support-inbox .support-thread-list') && css.includes('.support-client-group { display: block; overflow: visible; }'))
check('sessions use auto height and separate columns', css.includes('grid-template-columns: minmax(0, 1fr) auto;') && css.includes('height: auto;'))
check('horizontal and vertical resize handles are keyboard accessible', page.includes('aria-label="Змінити ширину списку чатів"') && page.includes('aria-label="Змінити висоту чатів"') && page.includes('onKeyDown={(event) => chatSize.onKeyDown'))
check('layout sizes survive reload', layout.includes('localStorage.getItem(key)') && layout.includes('localStorage.setItem(WIDTH_KEY') && layout.includes('localStorage.setItem(HEIGHT_KEY'))
check('resize mode disabled on narrow displays', layout.includes("'(max-width: 760px)'") && css.includes('height: auto !important;'))

// Execute the real framing parser with frames spanning arbitrary read() chunks.
const start = api.indexOf('export async function consumeOrderEvents(')
const end = api.indexOf('async function uploadChatPdf(', start)
assert.ok(start !== -1 && end > start)
const fn = api.slice(start, end).replace('export async function', 'async function')
const encoder = new TextEncoder()
const frames = [
  'event: support\ndata: {"eventId":"s1","kind":"support.changed","threadId":24,"direction":"in"}\n\n',
  'event: order\ndata: {"orderId":51,"kind":"order.changed"}\n\n',
  'event: support\ndata: {"threadId":"bad"}\n\n',
  'event: ready\ndata: {}\n\n',
].join('')
let readIndex = 0
const reader = { async read() { if (readIndex >= frames.length) return {done:true}; const size = readIndex % 4 + 1; const slice = frames.slice(readIndex, readIndex + size); readIndex += slice.length; return { done: false, value: encoder.encode(slice) } } }
const fakeFetch = async () => ({ok:true,status:200,body:{getReader:()=>reader}})
const consume = new Function('getToken','BASE','window','fetch','TextDecoder','ApiError', `${fn}\nreturn consumeOrderEvents`)(
  () => true, '/api', { location:{origin:'https://elfar.example'} }, fakeFetch, TextDecoder, Error,
)
const orderEvents=[], supportEvents=[]
await consume(payload => orderEvents.push(payload), {aborted:false}, payload => supportEvents.push(payload))
check('fragmented authenticated SSE carries one order event', orderEvents.length === 1 && orderEvents[0].orderId === 51)
check('fragmented SSE carries exactly one valid support event', supportEvents.length === 1 && supportEvents[0].threadId === 24)
check('support event is routed to each local chat and inbox', live.includes('elfar:support:changed') && messages.includes('Number(event.detail?.threadId) !== Number(id)') && page.includes("window.addEventListener('elfar:support:changed', changed)"))
check('SSE is a hint, not untrusted message body', source.includes('"threadId": thread_id') && !source.includes('"text": text') && router.includes("'support' if payload.get('kind')"))
check('Redis + in-process fallback emits support changes', source.includes('publish_support_changed') && source.includes('await _publish_payload(payload)') && source.includes('await _publish_local(payload)'))
check('staff, Mini App, and Telegram inbound emit invalidation', support.includes('emit_support_changed(thread_id, direction="out")') && shop.includes("emit_support_changed(thread_id, direction='in')") && bot.includes('emit_support_changed(thread.id, direction="in")'))
check('the same channel is used; no second SSE connection per page', live.includes('consumeOrderEvents') && !live.includes('consumeSupportEvents') && page.includes('<RealtimeOrders />'))
check('fallback polls when SSE is unavailable', messages.includes("kind === 'support' ? 3000 : 5000"))
check('notification sound comes only from global leader', notification.includes('if (!fresh.length || !isLeader()) return') && notification.includes("event.detail?.kind !== 'support.changed'"))
console.log(`\nSupport multiple windows: ${passed}/${passed}`)
