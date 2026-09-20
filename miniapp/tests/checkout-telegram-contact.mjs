import { readFileSync } from 'node:fs'

const checkout = readFileSync('src/screens/Checkout.jsx', 'utf8')
const telegram = readFileSync('src/telegram.js', 'utf8')
let bad = 0
const check = (ok, label) => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}`)
}

console.log('\n--- Telegram contact contract ---')
const requestBlock = telegram.slice(
  telegram.indexOf('export function requestContact()'),
  telegram.indexOf('export function canRequestContact()'),
)
check(requestBlock.includes('app.requestContact((granted)'),
      'requestContact трактує callback як boolean')
check(!requestBlock.includes('responseUnsafe') && !requestBlock.includes("get('contact')"),
      'Mini App не намагається читати номер із неіснуючого callback payload')
check(requestBlock.includes("contactRequested") && requestBlock.includes("status === 'sent'"),
      'підтримано офіційну подію contactRequested')
check(requestBlock.includes('setTimeout') && requestBlock.includes('15000'),
      'відсутній callback Telegram не зависає назавжди')

console.log('\n--- номер доходить через профіль ---')
const pull = checkout.slice(checkout.indexOf('const pullPhone'), checkout.indexOf('const set ='))
check(pull.includes('await api.contactPhone()'),
      'після дозволу Mini App чекає номер через легкий contact endpoint')
check(pull.includes('fresh?.phone'), 'номер береться з підтвердженого профілю')
check(pull.includes('phoneBusy'), 'повторне натискання кнопки заблоковане')
check(checkout.includes("contact_phone: f.contact_phone || normalizePhone(profile?.phone || '')"),
      'раніше підтверджений номер автоматично підставляється у checkout')

console.log('\n--- успішний checkout не зависає на «Оформлюємо…» ---')
const success = checkout.slice(checkout.indexOf("const payment ="), checkout.indexOf('} catch (err)', checkout.indexOf("const payment =")))
const doneAt = success.indexOf('onDone()')
const alertAt = success.indexOf('await alert(')
check(doneAt >= 0 && alertAt >= 0 && doneAt < alertAt,
      'checkout закриває pending-екран до нативного showAlert')
check(success.includes('submittingRef.current = false') && success.includes('setBusy(false)'),
      'busy/ref guard скидаються одразу після створення замовлення')
const alertBlock = telegram.slice(telegram.indexOf('export function alert(message)'), telegram.length)
check(alertBlock.includes('setTimeout(finish, 3500)'),
      'showAlert має timeout fallback і не може заблокувати success-flow')

console.log(`\nTELEGRAM CHECKOUT HOTFIX: ${bad ? `ПРОВАЛЕНО: ${bad}` : 'OK'}`)
process.exit(bad ? 1 : 0)
