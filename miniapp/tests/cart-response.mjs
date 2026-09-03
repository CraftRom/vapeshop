// Кошик відгукується на дотик одразу, а відмова не буває мовчазною.
//
// Три поломки, які цей набір стереже. Усі три однаково тихі: нічого не
// падає, у журналі чисто, а користуватись неможливо.
//
//   1. Кожне натискання «+» було окремим запитом, і лічильник не рухався,
//      поки той не повернеться. На телефоні з поганим звʼязком три швидкі
//      дотики виглядають як зламана кнопка: цифра стоїть, потім стрибає
//      на три.
//
//   2. Помилка зміни кошика не оброблялась ніде в ланцюгу. Обірваний
//      звʼязок або товар, який щойно розібрали, — і дотик просто не
//      робить нічого. Людина бачить товар у кошику, якого там немає, і
//      дізнається про це аж на оформленні.
//
//   3. Суми при цьому мусять лишатись серверними. Знижки, промокод і
//      бонуси рахує сервер, і намалювати їх наперед означало б показати
//      число, яке потім зміниться, — гірше за півсекунди очікування.
import { readFileSync } from 'node:fs'

const app = readFileSync('src/App.jsx', 'utf8')

let bad = 0
const check = (ok, label, detail = '') => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}${ok || !detail ? '' : ` — ${detail}`}`)
}

const block = (src, start, stop) => {
  const from = src.indexOf(start)
  if (from < 0) return ''
  const to = src.indexOf(stop, from + start.length)
  return to < 0 ? src.slice(from) : src.slice(from, to)
}

console.log('\n--- лічильник рухається одразу ---')
check(app.includes('pendingQty'), 'очікувані кількості тримаються окремо')
check(app.includes('const shownCart'),
      'є кошик «серверний плюс натиснуте» для показу')

const shown = block(app, 'const shownCart', '}, [cart, pendingQty])')
check(shown.includes('line.qty + pendingQty'),
      'кількість у рядку враховує ще не збережене')
check(!/total|subtotal|discount/.test(shown),
      'суми не перераховуються на клієнті — їх рахує сервер')

console.log('\n--- серія дотиків іде одним запитом ---')
const change = block(app, 'const changeCart = useCallback', '[flushCart],')
check(/setTimeout\(flushCart/.test(change),
      'відправка відкладена, а не негайна на кожен дотик')
check(change.includes('clearTimeout'),
      'попередній таймер знімається — інакше запити пішли б серією')
check(/pendingRef\.current\[productId\] = .*\+ delta/.test(change),
      'дельти накопичуються, а не перезаписуються')

console.log('\n--- відмова не буває мовчазною ---')
const flush = block(app, 'const flushCart = useCallback', '}, [])')
check(flush.includes('catch'), 'помилка перехоплюється')
check(flush.includes('setCartError'), 'причина показується людині')
check(flush.includes('api.cart()'),
      'після відмови стан перечитується з сервера, а не лишається вигаданим')
check(app.includes('cartError && ('),
      'смуга помилки є в розмітці')

console.log('\n--- очікуване не тримається вічно ---')
check(flush.includes('finally'),
      'накопичене прибирається і після успіху, і після відмови')

console.log('\n--- гроші показуються лише серверні ---')
// Найдорожча з можливих помилок тут: людина бачить одну суму, а
// списується інша.
check(/<Cart config=\{config\} cart=\{cart\}/.test(app),
      'кошик читає серверний стан, а не очікуваний')
check(/<Checkout\s+config=\{config\}\s+cart=\{cart\}/.test(app),
      'оформлення читає серверний стан')
check(app.includes('await flushCart()'),
      'перед оформленням незбережене дописується — інакше останнє '
      + 'натискання не потрапило б у замовлення')

console.log('\n--- миттєвий відгук там, де він потрібен ---')
// Каталог, сторінка товару і список бажаного — саме там тиснуть «+».
const consumers = (app.match(/cart=\{shownCart\}/g) || []).length
check(consumers >= 3,
      'екрани з кнопками отримують очікуваний кошик', `знайдено ${consumers}`)

console.log(`\nКОШИК: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
