// Відбір у панелі: фільтри живуть в адресі сторінки.
//
// Це та поломка, якої не видно в коді й не чути в скарзі. Менеджер
// відбирає «Прийняті» за минулий тиждень, відкриває замовлення,
// повертається — і бачить «Усі» з початку. Фільтр лежав у useState, а
// useState зникає разом із компонентом при переході. За зміну таких
// повернень десятки, і кожне коштує чотирьох дій заново.
//
// Друга частина набору — про порожній список. Порожньо через фільтр і
// порожньо взагалі це різні речі, а текст був один: менеджер відбирав за
// датою, нічого не знаходив і читав «щойно клієнт оформить замовлення,
// воно зʼявиться тут». Тобто панель повідомляла, що замовлень у магазині
// немає жодного.
import { readFileSync } from 'node:fs'

let bad = 0
const check = (ok, label, detail = '') => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}${ok || !detail ? '' : ` — ${detail}`}`)
}

const read = (p) => readFileSync(p, 'utf8')

const PAGES = {
  'Замовлення': 'src/pages/Orders.jsx',
  'Каталог': 'src/pages/Catalog.jsx',
  'Клієнти': 'src/pages/Customers.jsx',
  'Журнал': 'src/pages/Logs.jsx',
}

console.log('\n--- відбір переживає перехід на іншу сторінку ---')
for (const [title, path] of Object.entries(PAGES)) {
  const src = read(path)
  check(src.includes('useFilters('), `${title}: відбір в адресі сторінки`)
}

console.log('\n--- відбір не лишився в стані компонента ---')
// Найпростіший спосіб зламати це назад — дописати новий фільтр через
// useState поруч із рештою. Виглядатиме однорідно, а працюватиме інакше.
const FILTER_NAMES = [
  'search', 'status', 'dateFrom', 'dateTo', 'filter',
  'level', 'event', 'severity', 'since', 'until', 'limit', 'service',
]
for (const [title, path] of Object.entries(PAGES)) {
  const src = read(path)
  const stray = FILTER_NAMES.filter((name) =>
    new RegExp(`const \\[${name}, set`).test(src))
  check(stray.length === 0, `${title}: жодного фільтра в useState`, stray)
}

console.log('\n--- порожній список пояснює причину ---')
for (const [title, path] of [
  ['Замовлення', PAGES['Замовлення']],
  ['Каталог', PAGES['Каталог']],
  ['Клієнти', PAGES['Клієнти']],
]) {
  const src = read(path)
  check(src.includes('Нічого не знайдено'),
        `${title}: порожньо через відбір — окремий текст`)
  check(/resetFilters/.test(src),
        `${title}: із порожнього списку можна скинути відбір одним дотиком`)
}

console.log('\n--- відкрите посилання зберігає відбір ---')
// Ефект скидання відбору виконується і на першому рендері. Без перевірки
// «сервіс справді змінили» він стирав би фільтри з надісланого посилання:
// колега шле «журнал безпеки, невдалі входи за вчора», а одержувач бачить
// усі записи підряд.
const logs = read(PAGES['Журнал'])
check(logs.includes('previousService'),
      'скидання відбору лише при справжній зміні журналу, не на монтуванні')
const effect = logs.slice(logs.indexOf('api.logs.events(service)'))
  .slice(0, logs.slice(logs.indexOf('api.logs.events(service)')).indexOf('}, [service])'))
check(/previousService\.current !== null/.test(effect),
      'перший рендер відбір не чіпає')

console.log('\n--- типове значення не засмічує адресу ---')
const hook = read('src/components/useFilters.js')
check(/value === defaults\[key\]/.test(hook),
      'значення за замовчуванням в адресу не пишеться')
check(/replace: true/.test(hook),
      'зміна фільтра не додає запис в історію — інакше «назад» довелося б '
      + 'тиснути стільки разів, скільки було уточнень')
check(/Number\.isFinite/.test(hook),
      'числовий фільтр повертається числом, а не рядком з адреси')

console.log(`\nВІДБІР У ПАНЕЛІ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
