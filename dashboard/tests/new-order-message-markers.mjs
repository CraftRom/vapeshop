// Нові замовлення й непрочитані повідомлення мають різні, сталі маркери.
import { readFileSync } from 'node:fs'

const read = (path) => readFileSync(path, 'utf8')
const status = read('src/components/OrderStatus.jsx')
const orders = read('src/pages/Orders.jsx')
const page = read('src/pages/OrderPage.jsx')
const css = read('src/styles.css')
const version = read('src/version.js')

let bad = 0
const check = (ok, label) => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}`)
}

const atLeast = (source, minimum) => {
  const found = source.match(/APP_VERSION\s*=\s*'(\d+)\.(\d+)\.(\d+)'/)
  if (!found) return false
  const have = found.slice(1).map(Number)
  const need = minimum.split('.').map(Number)
  for (let i = 0; i < 3; i += 1) {
    if (have[i] !== need[i]) return have[i] > need[i]
  }
  return true
}

console.log('\n--- new order / message markers 1.39.0 ---')
check(status.includes('export function isNewOrderStatus') && status.includes('orderDisplayStatus(order, crmStatuses)'),
  'ознака нового CRM-замовлення походить із того самого display-model статусу')
check(!status.includes("statusId === 1") && !status.includes("crm_status_id === '1'"),
  'CRM statusId не захардкоджений')
check(status.includes("['новий', 'нове', 'new']"),
  'підтримані нормалізовані назви початкового статусу')
check(orders.includes("' is-new-order'") && orders.includes('order-new-flag'),
  'рядок і явний бейдж позначають нове замовлення')
check(orders.includes('orders-attention-summary') && orders.includes('unreadTotal') && orders.includes('newOrders'),
  'над списком є окремий summary нових замовлень і повідомлень')
check(orders.includes('orders?.reduce((sum, order) => sum + Number(unread[order.id] || 0), 0)'),
  'summary непрочитаних рахує тільки видимі після фільтрів замовлення')
check(page.includes('api.orders.messages(id),') && page.includes("message.direction === 'in' && !message.is_read"),
  'картка спершу отримує непрочитані, не гасячи їх до побудови UI')
check(page.includes('api.orders.markMessagesRead(id).catch(() => {})'),
  'після фіксації маркерів серверний unread-лічильник гаситься окремим lightweight endpoint')
check(page.includes('loadedOrderRef') && page.includes('setNewMessageIds((current) =>'),
  'повторний load у тій самій картці не стирає локальні маркери')
check(page.includes('new-messages-divider') && page.includes('bubble-new-badge') && page.includes('chat-new-counter'),
  'в чаті є межа нових реплік, бейдж на повідомленні та лічильник')
check(page.includes('order-new-order-chip') && page.includes('isNewOrderStatus(order, crmStatuses)'),
  'у шапці картки нове замовлення позначене тим самим правилом')
check(page.includes("window.location.hash !== '#chat'") && page.includes("document.getElementById('chat')?.scrollIntoView"),
  'клік по мітці непрочитаного веде безпосередньо до листування')
check(css.includes('.order-row.is-new-order.has-unread-messages') && css.includes('.bubble.is-new') && css.includes('.new-messages-divider'),
  'стилі одночасно розрізняють нове замовлення та нове повідомлення')
check(css.includes('.order-status-badge.is-new') && css.includes('.order-new-order-chip'),
  'початковий статус і картка мають узгоджений акцент')
check(atLeast(version, '1.39.0'), 'версія панелі не нижча за 1.39.0')

console.log(`\nNEW MARKERS: ${bad === 0 ? 'OK' : `FAIL: ${bad}`}`)
process.exit(bad ? 1 : 0)
