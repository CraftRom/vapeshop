// Перевірка полів при оформленні.
//
// Оформлення — єдиний екран, де помилка коштує грошей: людина не
// розібралася, чому кнопка не спрацювала, і пішла. Раніше всі пʼять
// обовʼязкових полів давали один банер угорі з переліком, а підсвічувався
// лише телефон. На екрані телефона з семи полів видно два, тож людина
// читала речення й шукала очима, яке саме поле пропустила — при тому що
// банер міг лишитися вище за межею екрана.
import { readFileSync } from 'node:fs'

const src = readFileSync('src/screens/Checkout.jsx', 'utf8')

let bad = 0
const check = (ok, label, detail = '') => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}${ok || !detail ? '' : ` — ${detail}`}`)
}

console.log('\n--- помічаються всі порожні поля, не лише телефон ---')
const submit = src.slice(src.indexOf('const submit ='), src.indexOf('setBusy(true)'))
check(/REQUIRED\.map\(\[?\(?\[key\]\)? => \[key, true\]\)/.test(submit)
      || submit.includes('REQUIRED.map(([key]) => [key, true])'),
      'при відправці всі обовʼязкові поля стають поміченими')
check(!submit.includes("setTouched({ contact_phone: true })"),
      'помічається не лише телефон')

console.log('\n--- людину ведуть до першого пропущеного ---')
check(submit.includes('scrollIntoView'),
      'екран прокручується до поля, а не лишає банер за межею видимого')
check(submit.includes('.focus('),
      'у поле ставиться курсор')
check(submit.includes('setTimeout'),
      'фокус із затримкою: інакше клавіатура Telegram гасить прокрутку')

console.log('\n--- у кожного поля власна підказка ---')
const required = src.slice(src.indexOf('const REQUIRED'), src.indexOf('const missing'))
for (const key of ['contact_surname', 'contact_name', 'contact_phone',
                   'city', 'address']) {
  check(required.includes(`'${key}'`), `${key} у переліку обовʼязкових`)
}
// Порядок у переліку має збігатися з порядком полів на екрані — за ним
// вибирається, куди прокрутити. Розбіжність відправила б людину не туди.
const order = ['contact_surname', 'contact_name', 'contact_phone', 'city', 'address']
const listed = order.map((k) => required.indexOf(`'${k}'`))
check(listed.every((v, i) => i === 0 || v > listed[i - 1]),
      'порядок у переліку збігається з порядком полів на екрані', listed)

console.log('\n--- підсвітка однакова для всіх полів ---')
// Один помічник на всі: інакше підсвітка з часом розійдеться —
// у телефона вона є, у решти немає, і саме так було до цієї правки.
check(src.includes('const cls =') && src.includes('const hint ='),
      'підсвітка й підказка йдуть через спільні помічники')
for (const id of ['surname', 'name', 'city', 'address']) {
  const field = src.slice(src.indexOf(`id="${id}"`), src.indexOf(`id="${id}"`) + 300)
  check(field.includes('cls('), `поле ${id} підсвічується`)
}

console.log('\n--- порожнє поле не показує дві помилки одразу ---')
// Порожній телефон — це «вкажіть телефон», а не «номер має 9 цифр».
check(src.includes("!blank('contact_phone')"),
      'у порожньому телефоні не зʼявляється ще й скарга на формат')

console.log('\n--- довідник Нової пошти ---')
// Раніше тут були два вільні рядки: люди писали «Київ, НП 12» або
// «відділення №12», і менеджер вгадував, яке саме з трьох. Помилка тут
// коштує повернення посилки, тож перевіряємо не наявність довідника, а
// рішення, які легко зробити навпаки.

// Зміна міста мусить скидати вибране відділення — і текст, и код.
// Інакше посилка поїде в нове місто зі старим кодом, і побачать це аж
// на відправці.
const changeCity = src.slice(src.indexOf('const changeCity'),
                             src.indexOf('const pickCity'))
check(changeCity.includes("address: ''")
      && changeCity.includes("delivery_warehouse_ref: ''"),
      'зміна міста скидає вибране відділення')
check(changeCity.includes("delivery_city_ref: ''"),
      'разом із текстом скидається й код міста')

// Код зберігається ПОРУЧ із текстом, а не замість: текст лишає
// замовлення читабельним і через рік, коли відділення закриють.
const pickPoint = src.slice(src.indexOf('const pickPoint'),
                            src.indexOf('const pickMethod'))
check(pickPoint.includes('address:') && pickPoint.includes('delivery_warehouse_ref:'),
      'вибір відділення зберігає і назву, і код')

// Перемикання способу доставки не має лишати «Відділення №7» як вулицю.
const pickMethod = src.slice(src.indexOf('const pickMethod'),
                             src.indexOf('const chosenPoint'))
check(pickMethod.includes("address: ''"),
      'перехід на курʼєра очищає поле адреси')

// Без ключа або при недоступному довіднику форма мусить лишатися
// придатною: краще прийняти замовлення й уточнити в чаті, ніж
// втратити покупця через чужу недоступність.
check(src.includes('directoryDown') && src.includes('err.status === 503'),
      'недоступний довідник повертає ручний ввід, а не блокує оформлення')
check(!/disabled=\{[^}]*directory/.test(src),
      'кнопка підтвердження не залежить від довідника')

// Запит на кожну натиснуту літеру — це шість звернень до перевізника
// на слово «Дніпро».
check(src.includes('setTimeout') && src.includes('clearTimeout'),
      'пошук міста йде з паузою, а не на кожну літеру')

// Поштомат не приймає накладений платіж.
check(src.includes('is_postomat') && src.includes("payment_method === 'cod'"),
      'накладений платіж у поштомат не пропускається')

console.log('\n--- попередній розрахунок доставки ---')
// Він мусить бути видимим і тоді, коли довідник вимкнений: без ключа
// покупець інакше не бачив би про вартість доставки нічого взагалі.
check(src.includes('form.city.trim().length > 1'),
      'вписане руками місто теж дає розрахунок')
check(/shipping\.cost \|\| shipping\.cost_from > 0/.test(src),
      'порожній блок із прочерком не показується')
check(src.includes('Точну суму називає перевізник'),
      'сказано, що число приблизне й уточнюється в менеджера')
check(src.includes('у підсумок вище не'),
      'сказано, що доставка не входить у суму замовлення')

console.log(`\nОФОРМЛЕННЯ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
