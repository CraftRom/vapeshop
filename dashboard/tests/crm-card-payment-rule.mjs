import fs from 'node:fs'
import {
  crmBusinessOutcomeName,
  crmStatusAllowsCalculatedCardPayment,
} from '../src/crmStatus.js'

const page = fs.readFileSync('src/pages/OrderPage.jsx', 'utf8')
const status = fs.readFileSync('src/components/OrderStatus.jsx', 'utf8')
const css = fs.readFileSync('src/styles.css', 'utf8')

const negative = ['Відмова', 'Повернення', 'Повернено', 'Видалений', 'Видалено', 'returned', 'deleted']

const checks = [
  ['Продаж is the only positive sale outcome', crmBusinessOutcomeName('Продаж') === 'sale'],
  ['Відправлений stays operational/pending', crmBusinessOutcomeName('Відправлений') === 'pending'],
  ['all refusal/return/deleted labels are negative outcomes', negative.every((name) => crmBusinessOutcomeName(name) === 'refusal')],
  ['Відправлений allows calculated card payment', crmStatusAllowsCalculatedCardPayment('Відправлений')],
  ['Продаж allows calculated card payment', crmStatusAllowsCalculatedCardPayment('Продаж')],
  ['negative outcomes never allow calculated payment', negative.every((name) => !crmStatusAllowsCalculatedCardPayment(name))],
  ['unknown status does not invent payment', !crmStatusAllowsCalculatedCardPayment('Custom terminal status')],
  ['dictionary order is not used as payment history', !status.includes('currentIndex >= shippedIndex')],
  ['dictionary order is not rendered as passed history', !status.includes('const passed = index < currentIndex')],
  ['status UI explicitly explains that dictionary is not history', status.includes('не означає, що заявка його проходила')],
  ['card payment rule uses semantic CRM helper', page.includes('isShippedOrLaterCrmStatus(order, crmStatuses)')],
  ['negative CRM outcome cancels synthetic payment confirmation', page.includes('isNegativeCrmOutcome(order, crmStatuses)')],
  ['raw SalesDrive payment fields are not overwritten', !page.includes('snap.payedAmount = total') && !page.includes('snap.restPay = 0')],
  ['calculated payment remains explicitly marked when valid', page.includes('Розрахунково оплачено') && css.includes('.crm-finance-rule-chip')],
  ['negative current status has separate visual state', css.includes('.crm-status-step.current.negative')],
]

let failed = 0
for (const [name, ok] of checks) {
  console.log(`${ok ? '✓' : '✗'} ${name}`)
  if (!ok) failed++
}
if (failed) process.exit(1)
console.log(`✓ CRM card payment rule: ${checks.length}/${checks.length}`)
