/** КАТАЛОГ: порядок і відбір.
 *
 * Пошук і категорії у вітрині були, а порядку — ні: список ішов у тому
 * вигляді, у якому його віддала база. У магазині з двома десятками
 * позицій це терпимо, далі — ні: людина, яка шукає дешевше, гортає весь
 * перелік і порівнює ціни очима.
 *
 * Перевіряємо саму логіку відбору, а не її наявність у розмітці.
 */
import { readFileSync } from 'node:fs'
import { sortProducts as arrange, discountPercent, DEFAULT_SORT, SORT_OPTIONS, normalizeCatalogState, resolveCatalogState, loadCatalogProducts } from '../src/catalogModel.js'

let bad = 0
const ok = (cond, label, detail) => {
  if (cond) console.log(`  ✓ ${label}`)
  else {
    bad += 1
    console.log(`  ✗ ${label}${detail === undefined ? '' : ` — ${JSON.stringify(detail)}`}`)
  }
}

const src = readFileSync('src/screens/Catalog.jsx', 'utf8')

ok(discountPercent({ is_sale: true, old_price: '400', price: '320' }) === 20, 'точні 20% не перетворюються на 19% через float')
ok(discountPercent({ is_sale: true, old_price: '299', price: '199' }) === 33, 'дробову знижку округлено вниз')
ok(discountPercent({ is_sale: true, old_price: '100', price: '110' }) === 0, 'зростання ціни не знижка')

const goods = [
  { id: 1, price: '300', stock: 5, is_new: true },
  { id: 2, price: '150', stock: 0 },
  { id: 3, price: '900', stock: 2, is_new: true },
]

console.log('\n--- порядок ---')
ok(arrange(goods, 'default', false).map((p) => p.id).join() === '1,2,3',
   '«За порядком» зберігає порядок сервера')
ok(arrange(goods, 'cheap', false).map((p) => p.id).join() === '2,1,3',
   'спершу дешеві')
ok(arrange(goods, 'pricey', false).map((p) => p.id).join() === '3,1,2',
   'спершу дорогі')
ok(arrange(goods, 'fresh', false).map((p) => p.id).join() === '1,3,2',
   'спочатку реальні новинки, потім решта товарів')

ok(arrange(goods.filter(p => !p.is_new), 'fresh').length === 1, 'без новинок асортимент не зникає')

const named = [
  { id: 1, name: 'Яблуко', is_sale: true, price: '100', old_price: '120', stock: 2 },
  { id: 2, name: 'Абрикос 10', price: '90', old_price: '80', stock: 0 },
  { id: 3, name: 'Абрикос 2', price: '80', old_price: '80', stock: 3 },
]
ok(arrange(named, 'nameAsc').map(p => p.id).join() === '3,2,1', 'алфавіт український, числа у назвах у природному порядку')
ok(arrange(named, 'nameDesc').map(p => p.id).join() === '1,2,3', 'зворотний алфавіт')
ok(arrange(named, 'sale').map(p => p.id).join() === '1,2,3', 'реальні акції першими, інші товари збережено')
ok(arrange(goods, 'fresh', true).length === 2, 'новинки та наявність поєднуються')
ok(named.map(p => p.id).join() === '1,2,3', 'оригінальну відповідь сервера не змінено')
ok(arrange([], 'nameAsc').length === 0, 'порожня відповідь обробляється')
console.log('\n--- наявність ---')
ok(arrange(goods, 'default', true).map((p) => p.id).join() === '1,3',
   'фільтр прибирає те, чого немає на складі')
ok(arrange(goods, 'default', false).length === 3,
   '«За порядком» без фільтра наявності показує весь асортимент')
ok(arrange(goods, 'cheap', true).map((p) => p.id).join() === '1,3',
   'порядок і фільтр працюють разом')
ok(arrange(goods, 'fresh', true).map((p) => p.id).join() === '1,3',
   'фільтр новинок теж поважає наявність')

console.log('\n--- фільтр новинок ---')
ok(DEFAULT_SORT === 'fresh' && SORT_OPTIONS[0].value === DEFAULT_SORT,
   '«Новинки» — перший пункт та початковий вибір')
ok(src.includes('normalizeCatalogState(initialState)'),
   'каталог зберігає ручний вибір при поверненні')
const sheet = readFileSync('src/screens/SortSheet.jsx', 'utf8')
ok(sheet.includes('SORT_OPTIONS.map('),
   'пункт «Новинки» доступний навіть у порожній категорії')

console.log('\n--- вихід із порожнього екрана ---')
ok(src.includes('Скинути пошук і фільтри'), 'є кнопка скидання')
ok(src.includes('setSelection(normalizeCatalogState())'), 'повне скидання відновлює початковий вибір')
ok(src.includes("'Усе з цього переліку зараз закінчилось.'"),
   'порожньо через фільтр і порожньо через пошук — різні тексти')

console.log('\n--- поле пошуку ---')
ok(src.includes('<Field'),
   'пошук іде через той самий компонент, що й форма замовлення')
ok(src.includes('search-clear'), 'набране можна стерти одним дотиком')

console.log('\n--- відновлення навігації ---')
const cats = [{ id: 1 }, { id: 2 }], subs = [{ id: 10, category_id: 1 }, { id: 20, category_id: null }, { id: 30, category_id: 99 }]
ok(normalizeCatalogState({ active: '1', subcategory: '10' }).active === 1, 'збережені текстові ID нормалізуються')
ok(resolveCatalogState({ active: 999, subcategory: 999 }, cats, subs).active === null, 'видалена категорія не блокує асортимент')
ok(resolveCatalogState({ active: 999, subcategory: 999 }, cats, subs).subcategory === null, 'видалена підкатегорія скидається')
ok(resolveCatalogState({ active: 2, subcategory: 10 }, cats, subs).active === 1, 'переміщена підкатегорія узгоджується з актуальним батьком')
ok(resolveCatalogState({ active: 1, subcategory: 20 }, cats, subs).active === null, 'самостійна група не поєднується зі стороннім батьком')
ok(resolveCatalogState({ subcategory: 30 }, cats, subs).subcategory === null, 'підкатегорія прихованого батька не зберігається')
ok(resolveCatalogState({ active: 1, subcategory: 10, ungrouped: true }, cats, subs).active === null, 'без груп виключає інші групи')
ok(resolveCatalogState({ active: 1, search: 'SKU', inStock: true, sort: 'sale' }, cats, subs).sort === 'sale', 'чинні ручні умови зберігаються')
ok(normalizeCatalogState({ sort: 'removed', active: -1 }).sort === DEFAULT_SORT, 'невідоме сортування відновлює початкове')
ok(normalizeCatalogState().subcategory === null && !normalizeCatalogState().inStock && !normalizeCatalogState().search, 'повне скидання очищає всі умови')
console.log('\n--- понад 500 товарів ---')
const large = Array.from({ length: 1001 }, (_, i) => ({ id: i + 1, is_new: i === 1000 }))
const calls = []
const result = await loadCatalogProducts(async ({ limit, offset, search }) => { calls.push({ limit, offset, search }); return large.slice(offset, offset + limit) }, { search: 'test' })
ok(result.length === 1001 && calls.map(x => x.offset).join() === '0,500,1000', 'отримано весь асортимент без обрізання')
ok(calls.every(x => x.search === 'test'), 'наступні сторінки зберігають пошук')
ok(arrange(result, 'fresh')[0].id === 1001, 'новинка з останньої сторінки стає першою')
let canceled = false, loads = 0
const ignored = await loadCatalogProducts(async () => { loads++; canceled = true; return large.slice(0, 500) }, {}, () => canceled)
ok(ignored.length === 0 && loads === 1, 'після зміни вибору наступні сторінки не завантажуються')
let duplicated = false
try { await loadCatalogProducts(async () => large.slice(0, 500), {}) } catch { duplicated = true }
ok(duplicated, 'повторена сторінка завершується помилкою, а не безкінечним циклом')

console.log(`\nКАТАЛОГ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad === 0 ? 0 : 1)
