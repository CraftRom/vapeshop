import fs from 'node:fs'

const page = fs.readFileSync('src/pages/OrderPage.jsx', 'utf8')
const chat = fs.readFileSync('src/components/useChatMessages.js', 'utf8')
const viewport = fs.readFileSync('src/components/useChatViewport.js', 'utf8')
const status = fs.readFileSync('src/components/OrderStatus.jsx', 'utf8')
const css = fs.readFileSync('src/styles.css', 'utf8')

const checks = [
  ['message send appends locally', page.includes('appendSentMessage: onSent') && page.includes('onSent(result.message)')],
  ['legacy broad onSent load removed', !page.includes('onSent={load}')],
  ['message polling is isolated', chat.includes('useVisiblePolling(refresh, 5000)')],
  ['message polling uses delta after_id instead of full history every cycle', chat.includes('api.orders.messages(id, false, after, null, 200)')],
  ['message receipts are periodically reconciled', chat.includes('tick.current % 6 === 0')],
  ['order polling is fallback-only behind realtime', page.includes('useVisiblePolling(refreshLocalOrder, 15000)') && page.includes("elfar:orders:changed")],
  ['background order refresh protects TTN draft', page.includes('trackingDirtyRef.current')],
  ['background order refresh protects manager note', page.includes('noteDirtyRef.current')],
  ['chat only follows bottom when manager is already there', viewport.includes('if (layout.current.bottom) node.scrollTop = node.scrollHeight')],
  ['CRM dictionary is not falsified into transition history', !status.includes('const passed = index < currentIndex') && status.includes('не означає, що заявка його проходила')],
  ['CRM status list has current and negative outcome states', css.includes('.crm-status-step.current') && css.includes('.crm-status-step.current.negative')],
  ['CRM stages adapt without horizontal scrolling', css.includes('grid-template-columns: repeat(auto-fit, minmax(118px, 1fr))') && !/\.crm-status-progress\s*\{[^}]*overflow-x:\s*auto/s.test(css)],
  ['SalesDrive TTN source is explicit', page.includes('сформована в SalesDrive') && page.includes('внесена вручну в SalesDrive')],
  ['CRM TTN delivery status is shown', page.includes('crmDeliveryStatus') && page.includes('Оновлено в CRM')],
]

let failed = 0
for (const [name, ok] of checks) {
  console.log(`${ok ? '✓' : '✗'} ${name}`)
  if (!ok) failed++
}
if (failed) process.exit(1)
console.log(`✓ Order live sync UX: ${checks.length}/${checks.length}`)
