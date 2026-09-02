// Підключення «Збереженого» до застосунку.
//
// Три поломки, які цей набір стереже, — це одна й та сама помилка на
// різних рівнях: стан є, а показати його нікому.
//
//   1. Списки не читались при відкритті застосунку взагалі. refresh()
//      брав кошик, профіль і замовлення, а списки — ні. Через це
//      «Збережене» в профілі виглядало порожнім, поки список не створили
//      й не видалили, вибір списку при «Відкласти» не мав що показати,
//      а назва «Список N» підбиралась за порожнім переліком і щоразу
//      збігалася з наявною — рівно ті 409, що видно в журналі.
//
//   2. Вікно вибору списку малювалось лише на сторінці товару. Кнопка
//      «Відкласти» в каталозі виставляла стан, показувати який було
//      нікому: людина тиснула, нічого не відбувалося, а вікно вискакувало
//      аж коли вона відкривала товар.
//
//   3. Те саме вікно стояло всередині екрана фатальної помилки, куди
//      воно не потрапить ніколи.
import { readFileSync } from 'node:fs'

const app = readFileSync('src/App.jsx', 'utf8')
const wl = readFileSync('src/screens/Wishlists.jsx', 'utf8')

let bad = 0
const check = (ok, label, detail = '') => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}${ok || !detail ? '' : ` — ${detail}`}`)
}

/** Тіло функції за назвою — від оголошення до рядка-закривача. */
const block = (src, start, stop) => {
  const from = src.indexOf(start)
  if (from < 0) return ''
  const to = src.indexOf(stop, from)
  return to < 0 ? src.slice(from) : src.slice(from, to)
}

console.log('\n--- списки читаються при відкритті ---')
const refresh = block(app, 'const refresh = useCallback', '}, [])')
check(refresh.includes('api.wishlists.list'),
      'refresh() читає списки бажаного')
check(refresh.includes('setWishlists'),
      'прочитане потрапляє в стан')

console.log('\n--- вікно вибору списку доступне з каталогу ---')
// Екран фатальної помилки й сторінка товару — окремі гілки return.
// Вікно має бути і в головному розкладі, інакше кнопка в каталозі німа.
const fatal = block(app, 'if (fatal) {', 'if (!config)')
check(!fatal.includes('SavePicker'),
      'вікна немає на екрані фатальної помилки, куди воно не потрапить')

const pickers = (app.match(/<SavePicker/g) || []).length
check(pickers >= 2,
      'вікно малюється і на сторінці товару, і в головному розкладі',
      `знайдено ${pickers}`)

const main = app.slice(app.lastIndexOf("tab === 'profile'"))
check(main.includes('<SavePicker'),
      'у розкладі з вкладками вікно є — інакше «Відкласти» в каталозі мовчить')

console.log('\n--- окрема сторінка списку ---')
check(wl.includes('export function WishlistPage'),
      'сторінка списку існує')
check(app.includes('<WishlistPage'),
      'застосунок її відкриває')
check(app.includes('setOpenListId(null)') && app.includes('backButton'),
      'із неї є вихід кнопкою «назад»')

const page = block(wl, 'export function WishlistPage', '\n}\n')
check(page.includes('<ProductCard'),
      'товари показані тією самою карткою, що й у каталозі')
check(page.includes('onOpenProduct'), 'звідси можна відкрити товар')
check(page.includes('onCartChange'), 'звідси можна покласти в кошик')
check(page.includes('wishlists.toggle'), 'звідси можна прибрати зі списку')

console.log('\n--- відкритий список не застаріває ---')
// Тримаємо номер, а не копію: після прибирання товару приходить
// оновлений список, і копія показувала б те, що вже прибрали.
check(app.includes('const [openListId'),
      'у стані лежить номер списку, а не його копія')
check(/wishlists \|\| \[\]\)\.find\(\(w\) => w\.id === openListId\)/.test(app),
      'список щоразу береться з переліку заново')

console.log(`\nЗБЕРЕЖЕНЕ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
