import {readSourceCss} from './helpers/source-css.mjs'
import fs from 'node:fs'
import {paymentMeta} from '../src/commerce.js'

const page = fs.readFileSync(new URL('../src/pages/OrderPage.jsx', import.meta.url), 'utf8')
const orders = fs.readFileSync(new URL('../src/pages/Orders.jsx', import.meta.url), 'utf8')
const css = readSourceCss()
const version = fs.readFileSync(new URL('../src/version.js', import.meta.url), 'utf8')

const checks = [
  ['оплата винесена окремим помітним блоком', page.includes('order-payment-summary')],
  ['переказ на картку названо прямо', paymentMeta('card').title==='Переказ за реквізитами'],
  ['накладений платіж названо прямо', paymentMeta('cod').title==='Оплата при отриманні'],
  ['для картки пояснено, коли ставити «Оплачено»', page.includes('переведіть замовлення в статус «Оплачено»')],
  ['для накладеного платежу пояснено оплату при отриманні', page.includes('Клієнт сплачує при отриманні')],
  ['сума показана в блоці оплати', page.includes('money(order.total)') && page.includes('order-payment-amount')],
  ['у шапці замовлення є позначка способу оплати', page.includes('order-head-payment') && css.includes('.order-head-payment')],
  ['скасоване замовлення не виглядає як неоплачене', page.includes("paymentIsCancelled") && page.includes('Замовлення скасовано')],
  ['є мобільна розкладка блоку оплати', css.includes('@media (max-width: 760px)') && css.includes('.order-payment-summary')],
  ['у списку є окрема колонка «Оплата»', orders.includes('<span>Оплата</span>') && orders.includes('order-payment-cell')],
  ['спосіб оплати більше не захований у заголовку статусу', !orders.includes('className="order-payment"')],
  ['обидва способи оплати підписані однозначно', paymentMeta('card').title!==paymentMeta('cod').title && paymentMeta(null).title.includes('не вказано')],
  ['накладений платіж прямо пояснює оплату при отриманні', paymentMeta('cod').title.includes('при отриманні')],
  ['для картки є явна візуальна ознака', paymentMeta('card').icon==='💳' && css.includes('.order-payment-method.card')],
  ['для накладеного платежу є явна візуальна ознака', paymentMeta('cod').icon==='📦' && css.includes('.order-payment-method.cod')],
  ['на вузьких екранах оплата стає окремим блоком картки', css.includes('"payment payment"') && css.includes('.order-payment-cell { grid-area: payment; }')],
  ['швидкий перегляд використовує той самий зрозумілий блок оплати', orders.includes('order-quick-payment') && orders.includes('<OrderPaymentMethod order={order} />')],
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
