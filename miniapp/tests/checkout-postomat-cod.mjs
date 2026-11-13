/** Regression: накладений платіж у поштоматі не є забороненою комбінацією.
 * Запуск: cd miniapp && node tests/checkout-postomat-cod.mjs
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const checkout = readFileSync('src/screens/Checkout.jsx', 'utf8')
const success = readFileSync('src/screens/OrderSuccess.jsx', 'utf8')
const backend = readFileSync('../backend/api/routers/shop.py', 'utf8')
const shipment = readFileSync('../backend/shop/services/shipment.py', 'utf8')
const css = readFileSync('src/styles.css', 'utf8')

let passed = 0
function check(name, condition) {
  assert.ok(condition, name)
  console.log(`PASS ${name}`)
  passed += 1
}
const submit = checkout.slice(checkout.indexOf('const submit ='), checkout.indexOf('const blank ='))
const destination = checkout.slice(checkout.indexOf('const chosenPoint'), checkout.indexOf('const applyPromo'))
const payment = checkout.slice(checkout.indexOf('id="sec-payment"'), checkout.indexOf('id="promo"'))

check('COD remains selectable', payment.includes("payment_method: 'cod'") && payment.includes("form.payment_method === 'cod'"))
check('Directory parcel-locker flag recognized', destination.includes('chosenPoint?.is_postomat'))
check('Manually typed parcel locker recognized', destination.includes('/поштомат/i.test(form.address)'))
check('Courier cannot be misidentified as parcel locker', destination.includes('toWarehouse &&'))
check('Locker+COD not blocked on submit', !/поштомат[^\n]*не приймають|поштомат[^\n]*недоступний|postomatCod[^\n]*return/.test(submit))
check('Payment hint states online payment before opening', payment.includes('postomatCod') && payment.includes('до відкриття комірки'))
check('Hint is informative, not field-error', !payment.includes('className="field-error"'))
check('Successful checkout returns locker-COD hint to confirmation', submit.includes('postomat_cod: postomatCod'))
check('Confirmation explains payment before opening', success.includes('order.postomat_cod') && success.includes('до відкриття комірки'))
check('Confirmation does not change normal COD messaging', success.includes('Оплата при отриманні.'))
check('Confirmation does not change card payment messaging', success.includes('Менеджер надішле реквізити'))
check('Backend accepts warehouse and COD independently', backend.includes('payment_method: str = Field(..., pattern="^(card|cod)$")') && backend.includes('delivery_method: str | None = Field(None, pattern="^(warehouse|courier)$")'))
check('Backend persists both delivery and payment options', backend.includes('payment_method=data.payment_method') && backend.includes('delivery_warehouse_ref=data.delivery_warehouse_ref'))
check('Shipment model maps COD onto the parcel', shipment.includes('cod_amount=total if order.payment_method == PAYMENT_COD else Decimal(0)'))
check('Payment hint uses theme tokens', css.includes('.postomat-cod-hint') && css.includes('var(--accent-soft)'))
console.log(`CHECKOUT POSTOMAT COD: ${passed}/${passed}`)
