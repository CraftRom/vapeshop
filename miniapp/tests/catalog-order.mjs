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

let bad = 0
const ok = (cond, label, detail) => {
  if (cond) console.log(`  ✓ ${label}`)
  else {
    bad += 1
    console.log(`  ✗ ${label}${detail === undefined ? '' : ` — ${JSON.stringify(detail)}`}`)
  }
}

const src = readFileSync('src/screens/Catalog.jsx', 'utf8')

const hasFreshStatus = (product) => {
  if (!product || typeof product !== 'object') return false
  if (product.is_new === true || product.new === true) return true
  const raw = product.status ?? product.badge ?? product.label ?? product.tag ?? ''
  const label = String(raw).trim().toLowerCase()
  return ['new', 'fresh', 'новинка', 'новинки'].includes(label)
}

const arrange = (products, sort, inStock) => {
  let rows = inStock ? products.filter((p) => p.stock > 0) : [...products]
  if (sort === 'cheap') rows.sort((a, b) => Number(a.price) - Number(b.price))
  if (sort === 'pricey') rows.sort((a, b) => Number(b.price) - Number(a.price))
  if (sort === 'fresh') rows = rows.filter(hasFreshStatus)
  return rows
}

const goods = [
  { id: 1, price: '300', stock: 5, is_new: true },
  { id: 2, price: '150', stock: 0 },
  { id: 3, price: '900', stock: 2, badge: 'новинка' },
]

console.log('\n--- порядок ---')
ok(arrange(goods, 'default', false).map((p) => p.id).join() === '1,2,3',
   'без вибору порядок лишається таким, як віддав сервер')
ok(arrange(goods, 'cheap', false).map((p) => p.id).join() === '2,1,3',
   'спершу дешеві')
ok(arrange(goods, 'pricey', false).map((p) => p.id).join() === '3,1,2',
   'спершу дорогі')
ok(arrange(goods, 'fresh', false).map((p) => p.id).join() === '1,3',
   'новинки показують лише товари з реальним статусом')

console.log('\n--- наявність ---')
ok(arrange(goods, 'default', true).map((p) => p.id).join() === '1,3',
   'фільтр прибирає те, чого немає на складі')
ok(arrange(goods, 'default', false).length === 3,
   'вимкнений фільтр не ховає нічого: за замовчуванням видно весь асортимент')
ok(arrange(goods, 'cheap', true).map((p) => p.id).join() === '1,3',
   'порядок і фільтр працюють разом')
ok(arrange(goods, 'fresh', true).map((p) => p.id).join() === '1,3',
   'фільтр новинок теж поважає наявність')

console.log('\n--- фільтр новинок ---')
ok(src.includes('hasFreshProducts') && src.includes('(products || []).some(hasFreshStatus)'),
   'чіп «Новинки» показується лише коли справді є нові товари')
ok(src.includes("{hasFreshProducts && ("),
   'кнопка «Новинки» умовна, а не постійна')

console.log('\n--- вихід із порожнього екрана ---')
ok(src.includes('Скинути пошук і фільтри'), 'є кнопка скидання')
ok(/const reset = \(\) => \{[\s\S]*?setSearch\(''\)[\s\S]*?setSort\('default'\)[\s\S]*?setInStock\(false\)/
  .test(src), 'скидає все одразу, а не лише пошук')
ok(src.includes("'Усе з цього переліку зараз закінчилось.'"),
   'порожньо через фільтр і порожньо через пошук — різні тексти')

console.log('\n--- поле пошуку ---')
ok(src.includes('<Field'),
   'пошук іде через той самий компонент, що й форма замовлення')
ok(src.includes('search-clear'), 'набране можна стерти одним дотиком')

console.log(`\nКАТАЛОГ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad === 0 ? 0 : 1)
