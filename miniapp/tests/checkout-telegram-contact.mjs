import { readFileSync } from 'node:fs'

const checkout = readFileSync('src/screens/Checkout.jsx', 'utf8')
const telegram = readFileSync('src/telegram.js', 'utf8')
const api = readFileSync('src/api.js', 'utf8')
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
check(requestBlock.includes('setTimeout') && requestBlock.includes('20000'),
      'відсутній callback Telegram не зависає назавжди')
check(requestBlock.includes('callbackGrace') && requestBlock.includes('1200'),
      'false callback не перемагає запізнілу contactRequested:sent подію')

console.log('\n--- номер доходить через профіль ---')
const pull = checkout.slice(checkout.indexOf('const pullPhone'), checkout.indexOf('const set ='))
check(pull.includes('await api.contactPhone()'),
      'після дозволу Mini App чекає номер через легкий contact endpoint')
check(pull.includes('fresh?.phone'), 'номер береться з підтвердженого профілю')
check(pull.includes('phoneBusy'), 'повторне натискання кнопки заблоковане')
check(pull.includes('granted ? 60 : 10'), 'після sent Mini App чекає асинхронний bot update до 30+ секунд')
check(pull.includes('storefront.contact.synced') && pull.includes('storefront.contact.sync_timeout'),
      'контактний bridge має діагностичні події без номера')
check(api.includes("cache: 'no-store'"), 'персональні GET Mini App не кешуються')
check(api.includes('/contact-phone?_='), 'contact endpoint має cache-busting nonce')
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
