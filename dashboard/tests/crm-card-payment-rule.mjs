import fs from 'node:fs'

const page = fs.readFileSync('src/pages/OrderPage.jsx', 'utf8')
const status = fs.readFileSync('src/components/OrderStatus.jsx', 'utf8')
const css = fs.readFileSync('src/styles.css', 'utf8')

const checks = [
  ['shipped-or-later helper exists', status.includes('isShippedOrLaterCrmStatus')],
  ['status order is taken from SalesDrive dictionary', status.includes('currentIndex >= shippedIndex')],
  ['shipped name is semantic rather than hard-coded ID', status.includes("name.startsWith('відправлен')")],
  ['card payment rule uses CRM stage', page.includes('const cardShippedOrLater = cardPayment && isShippedOrLaterCrmStatus(order, crmStatuses)')],
  ['card payment can be confirmed by local checkout or resolved CRM label', page.includes("order.payment_method === 'card' || crmPaymentText.includes('карт')")],
  ['effective paid amount becomes full CRM total', page.includes('const paid = cardShippedOrLater') && page.includes('? total : snap?.payedAmount')],
  ['effective rest becomes zero', page.includes('const rest = cardShippedOrLater') && page.includes('? 0 : snap?.restPay')],
  ['raw SalesDrive payment fields are not overwritten', !page.includes('snap.payedAmount = total') && !page.includes('snap.restPay = 0')],
  ['calculated payment is explicitly marked in UI', page.includes('Розрахунково оплачено') && css.includes('.crm-finance-rule-chip')],
  ['factual CRM wording is preserved when rule is inactive', page.includes('Фактичні суми із заявки SalesDrive')],
]

let failed = 0
for (const [name, ok] of checks) {
  console.log(`${ok ? '✓' : '✗'} ${name}`)
  if (!ok) failed++
}
if (failed) process.exit(1)
console.log(`✓ CRM card payment rule: ${checks.length}/${checks.length}`)
