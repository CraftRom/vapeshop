// CRM is the source of truth for order statuses shown in the dashboard.
import { readFileSync } from 'node:fs'

let bad = 0
const read = (p) => readFileSync(p, 'utf8')
const check = (ok, label) => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}`)
}

const api = read('src/api.js')
const status = read('src/components/OrderStatus.jsx')
const orders = read('src/pages/Orders.jsx')
const page = read('src/pages/OrderPage.jsx')
const customers = read('src/pages/Customers.jsx')
const overview = read('src/pages/Overview.jsx')

check(api.includes("salesdriveStatuses: () => request('/orders/salesdrive-statuses')"),
  'робочий UI читає довідник статусів через staff endpoint')
check(api.includes("body: { status_id: String(statusId) }"),
  'браузер надсилає лише statusId, а не довірену назву')
check(status.includes("if (order.crm_id)"),
  'CRM-linked замовлення відокремлені від legacy')
check(status.indexOf('fromDictionary') < status.indexOf('order.crm_status_name'),
  'актуальний CRM-довідник має пріоритет над історичним підписом')
check(orders.includes("value={`crm:${item.id}`}"),
  'фільтр статусів використовує реальні CRM statusId')
check(orders.includes('SalesDriveStatusSelect') && orders.includes('OrderStatusBadge'),
  'список замовлень показує й змінює CRM-статус одним компонентом')
check(page.includes('salesdriveRefresh') && page.includes('Прочитано з CRM'),
  'картка має пряме читання заявки та показує свіжість')
check(orders.includes('loadCrmStatuses, 300000') && page.includes('loadCrmStatuses, 300000'),
  'довідник CRM оновлюється у відкритій панелі')
check(customers.includes('OrderStatusBadge order={o}'),
  'історія клієнта використовує той самий display-model')
check(overview.includes('row.source') && overview.includes('StatusBadge'),
  'аналітика не змішує CRM та legacy статуси')

console.log(`\nCRM STATUS SOURCE: ${bad === 0 ? 'OK' : `FAIL: ${bad}`}`)
process.exit(bad ? 1 : 0)
