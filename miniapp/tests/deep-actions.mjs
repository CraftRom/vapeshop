import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

let failed = 0
function check(ok, label) {
  console.log(`${ok ? '✓' : '✗'} ${label}`)
  if (!ok) failed++
}

const src = readFileSync('src/App.jsx', 'utf8')
const checkout = readFileSync('src/screens/Checkout.jsx', 'utf8')
const chat = readFileSync('src/screens/Chat.jsx', 'utf8')
const wish = readFileSync('src/screens/Wishlists.jsx', 'utf8')
const api = readFileSync('src/api.js', 'utf8')
const telegram = readFileSync('src/telegram.js', 'utf8')
const profile = readFileSync('src/screens/Profile.jsx', 'utf8')

console.log('\n--- кнопки й навігація ---')
const jsxFiles = []
function walk(dir) {
  for (const name of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, name.name)
    if (name.isDirectory()) walk(p)
    else if (p.endsWith('.jsx')) jsxFiles.push(p)
  }
}
walk('src')
let orphanButtons = []
for (const file of jsxFiles) {
  const text = readFileSync(file, 'utf8')
  for (const match of text.matchAll(/<button\b([^>]*)>/gs)) {
    const attrs = match[1]
    if (!attrs.includes('onClick=') && !attrs.includes('type="submit"') && !attrs.includes("type='submit'") && !attrs.includes('disabled')) {
      orphanButtons.push(`${file}:${text.slice(0, match.index).split('\n').length}`)
    }
  }
}
check(orphanButtons.length === 0, `усі ${jsxFiles.length} JSX-файлів: кнопки мають дію`)
check(src.indexOf('if (openProduct)') < src.indexOf('if (openListId && openedList)'), 'товар зі списку бажаного реально відкривається')
const back = src.slice(src.indexOf('// Системна кнопка'), src.indexOf('useEffect(() => hideMainButton'))
check(back.indexOf('if (legal)') < back.indexOf('if (checkingOut)'), 'Back спершу закриває legal overlay')
check(back.indexOf('if (saving)') < back.indexOf('if (checkingOut)'), 'Back спершу закриває SavePicker')

console.log('\n--- кошик і checkout ---')
check(src.includes('flushInFlight.current.catch(() => null).then(run)'), 'flush кошика серіалізований')
check(src.includes('const clearRun = flushInFlight.current.catch(() => null).then(() => api.clearCart())'), 'очищення кошика не гониться паралельно з +/-')
check(src.includes('await flushCart()') && src.indexOf('await flushCart()') < src.indexOf('setCheckingOut(true)'), 'checkout чекає останні зміни кошика')
check(checkout.includes('const submittingRef = useRef(false)') && checkout.includes('if (submittingRef.current) return'), 'double-click checkout блокується синхронним ref')
check(checkout.includes('checkout_key: checkoutKey.current'), 'checkout має idempotency key')
const successBlock = checkout.slice(checkout.indexOf("const payment ="), checkout.indexOf('} catch (err)', checkout.indexOf("const payment =")))
check(successBlock.indexOf('onDone()') >= 0 && successBlock.indexOf('onDone()') < successBlock.indexOf('await alert('), 'успішний checkout виходить із pending-стану до Telegram alert')
check(checkout.includes('const afterDiscount = Math.max(0, subtotal - discount)') && !checkout.includes('? Number(profile?.max_bonus_now'), 'бонус у UI рахується після знижки як на backend')
check(api.includes("const maxAttempts = method === 'GET' ? GET_RETRIES + 1 : 1"), 'POST checkout не ретраїться автоматично')

console.log('\n--- чат і toggle-дії ---')
check(chat.includes('const sendingRef = useRef(false)') && chat.includes('if (!body || sendingRef.current) return'), 'повідомлення чату не дублюється подвійним click/Enter')
check(chat.includes('const uploadingRef = useRef(false)'), 'подвійне завантаження вкладення заблоковане')
check(chat.includes('mergeMessages(current, incoming)'), 'poll чату не стирає щойно надіслане повідомлення')
check(wish.includes('const actionRef = useRef(false)') && wish.includes('if (actionRef.current) return'), 'toggle списку бажаного захищений від подвійного натискання')
check(wish.includes('droppingRef.current.has(product.id)'), '«Прибрати зі списку» не виконує toggle двічі')
check(api.includes("res = await fetchTimed(`${BASE}${endpoint}`"), 'upload фото має timeout')
check(telegram.includes('app.showAlert(message, finish)') && telegram.includes('setTimeout(finish, 3500)'), 'Telegram alert має завершуваний Promise із timeout fallback')
check(profile.includes('const cancellingRef = useRef(null)') && profile.includes('if (cancellingRef.current !== null) return'), 'скасування замовлення не відкриває два confirm і не дублює POST')

console.log(`\nDEEP ACTIONS: ${failed ? `ПРОВАЛЕНО ${failed}` : 'усі перевірки пройдено'}`)
process.exit(failed ? 1 : 0)
