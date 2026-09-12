import fs from 'node:fs'

const page = fs.readFileSync(new URL('../src/pages/OrderPage.jsx', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
const version = fs.readFileSync(new URL('../src/version.js', import.meta.url), 'utf8')

const checks = [
  ['prominent payment summary exists', page.includes('order-payment-summary')],
  ['card transfer has explicit wording', page.includes("'Переказ на картку'")],
  ['cod has explicit wording', page.includes("'Накладений платіж'")],
  ['card flow explains paid status', page.includes('переведіть замовлення в статус «Оплачено»')],
  ['cod flow explains payment on receipt', page.includes('Клієнт сплачує при отриманні')],
  ['amount is shown in payment summary', page.includes('money(order.total)') && page.includes('order-payment-amount')],
  ['header has quick payment badge', page.includes('order-head-payment') && css.includes('.order-head-payment')],
  ['cancelled orders do not look like payment is pending', page.includes("paymentIsCancelled") && page.includes('Замовлення скасовано')],
  ['mobile payment layout exists', css.includes('@media (max-width: 760px)') && css.includes('.order-payment-summary')],
  ['version bumped', version.includes("1.31.8")],
]

let failed = 0
for (const [name, ok] of checks) {
  console.log(`${ok ? 'PASS' : 'FAIL'}: ${name}`)
  if (!ok) failed++
}
if (failed) process.exit(1)
console.log(`PASS: ${checks.length}/${checks.length}`)
