import fs from 'node:fs'

const page = fs.readFileSync(new URL('../src/pages/OrderPage.jsx', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
const version = fs.readFileSync(new URL('../src/version.js', import.meta.url), 'utf8')

const checks = [
  ['оплата винесена окремим помітним блоком', page.includes('order-payment-summary')],
  ['переказ на картку названо прямо', page.includes("'Переказ на картку'")],
  ['накладений платіж названо прямо', page.includes("'Накладений платіж'")],
  ['для картки пояснено, коли ставити «Оплачено»', page.includes('переведіть замовлення в статус «Оплачено»')],
  ['для накладеного платежу пояснено оплату при отриманні', page.includes('Клієнт сплачує при отриманні')],
  ['сума показана в блоці оплати', page.includes('money(order.total)') && page.includes('order-payment-amount')],
  ['у шапці замовлення є позначка способу оплати', page.includes('order-head-payment') && css.includes('.order-head-payment')],
  ['скасоване замовлення не виглядає як неоплачене', page.includes("paymentIsCancelled") && page.includes('Замовлення скасовано')],
  ['є мобільна розкладка блоку оплати', css.includes('@media (max-width: 760px)') && css.includes('.order-payment-summary')],
  // Тут було «version bumped» із точним 1.32.1: падало на кожному випуску.
  ['версія панелі задана', /APP_VERSION = '\d+\.\d+\.\d+'/.test(version)],
]

let failed = 0
for (const [name, ok] of checks) {
  console.log(`  ${ok ? '✓' : '✗'} ${name}`)
  if (!ok) failed++
}
console.log(`\nОПЛАТА В ЗАМОВЛЕННІ: ${failed ? `ПРОВАЛЕНО: ${failed}` : 'усе витримано'}`)
if (failed) process.exit(1)
