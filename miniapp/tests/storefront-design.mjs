/** ДИЗАЙН ВІТРИНИ 2.12.0: один шар стилів і спільні правила розмітки.
 *
 * До 2.12.0 styles.css складався з шести нашарувань, кожне з яких
 * перебивало попереднє, а відступи дублювались inline-стилями в розмітці.
 * Звідси й дефекти: рейки від краю екрана, сердечко окремим рядком,
 * заставка каталогу замість товарів у видимій зоні. Тут стережемо, щоб
 * безлад не повернувся, а не те, як саме виглядає кожен піксель.
 *
 * Набір замінює ui-refresh.mjs: той перевіряв розмітку 2.11.0 (заставку
 * каталогу, яку прибрано) і не входив у run_all.sh, бо друкував OK/FAIL,
 * а зведення шукає лише ✓/✗.
 */
import { readFileSync, readdirSync } from 'node:fs'

let bad = 0
const ok = (cond, label, detail) => {
  if (cond) console.log(`  ✓ ${label}`)
  else {
    bad += 1
    console.log(`  ✗ ${label}${detail === undefined ? '' : ` — ${JSON.stringify(detail)}`}`)
  }
}

const css = readFileSync('src/styles.css', 'utf8')
const app = readFileSync('src/App.jsx', 'utf8')
const main = readFileSync('src/main.jsx', 'utf8')
const catalog = readFileSync('src/screens/Catalog.jsx', 'utf8')
const product = readFileSync('src/screens/ProductPage.jsx', 'utf8')

/** Тіло першого правила, у переліку селекторів якого є selector. */
const bare = css.replace(/\/\*[\s\S]*?\*\//g, '')
const block = (selector) => {
  // Коментарі прибираємо: інакше текст над правилом потрапляє в перелік
  // селекторів, і правило не знаходиться.
  for (const m of bare.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
    if (m[1].split(',').map((s) => s.trim()).includes(selector)) return m[2]
  }
  return ''
}
/** Тіло правила, у якого цей селектор — єдиний. */
const own = (selector) => {
  for (const m of bare.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
    if (m[1].trim() === selector) return m[2]
  }
  return ''
}
/** Скільки разів селектор відкриває правило з початку рядка. */
const defined = (selector) => css
  .split('\n')
  .filter((line) => line.startsWith(`${selector} {`)).length

console.log('\n--- один шар стилів ---')
ok(css.includes('DESIGN 2.12.0'), 'позначка поточного шару є')
ok(!/REFRESH 2\.\d+|2\.10\.1 flat|premium typography/.test(css),
   'старих нашарувань не лишилось')
ok(css.split('\n').filter((l) => l.startsWith(':root {')).length === 1,
   'типові токени оголошено один раз', css.split('\n').filter((l) => l.startsWith(':root {')).length)
for (const sel of ['.item', '.add', '.chip', '.tabs', '.bar', '.primary', '.stepper', '.heart', '.card']) {
  ok(defined(sel) === 1, `${sel} визначено один раз`, defined(sel))
}
// Типова тема — рівно дві копії (темна й світла). Третя означала б, що
// хтось знову зашив палітру поверх теми Telegram.
ok((css.match(/--tg-bg:/g) || []).length === 2, 'палітра Telegram не перезаписується поверх',
   (css.match(/--tg-bg:/g) || []).length)

console.log('\n--- поверхні від теми клієнта ---')
ok(block(':root').includes('--card: var(--tg-secondary-bg)'), 'темна: картка — вторинне тло теми')
ok(block(":root[data-scheme='light']").includes('--card: var(--tg-bg)'), 'світла: картка — основне тло теми')
ok(css.includes('@supports (color: color-mix('), 'лінії від кольору тексту, із запасом для старих WebView')

console.log('\n--- відступи з одного джерела ---')
ok(block('.rail').includes('var(--page-x)'), 'рейки мають те саме бічне поле, що й картки')
ok(block('.list').includes('var(--page-x)'), 'список товарів — те саме поле')
ok(block('.field').includes('var(--page-x)'), 'поля форми — те саме поле')
const screens = ['src/App.jsx', ...readdirSync('src/screens')
  .filter((f) => f.endsWith('.jsx') && f !== 'FieldDiag.jsx')
  .map((f) => `src/screens/${f}`)]
const inline = screens.filter((f) => readFileSync(f, 'utf8').includes('style={{'))
ok(inline.length === 0, 'розмітка не задає власних відступів inline-стилями', inline)

console.log('\n--- каталог і картка товару ---')
ok(!catalog.includes('catalog-hero'), 'заставка не відсуває товари за край екрана')
ok(app.includes('className="store-head"') && app.includes('config.shop_name'),
   'шапка в один рядок із назвою магазину')
const card = catalog.slice(catalog.indexOf('export function ProductCard'), catalog.indexOf('export function Catalog'))
const foot = card.slice(card.indexOf('className="item-foot"'), card.indexOf('className="item-side"'))
ok(foot.includes('heart'), '«відкласти» ділить рядок із наявністю, а не займає свій')
ok(!/item-title[^"]*clamp/.test(card) && !block('.item-title').includes('line-clamp'),
   'назва не обрізається: міцність і смак стоять у її кінці')
ok(block('.add').includes('var(--accent-soft)'), 'кнопка в картці тональна, а не залита')
ok(own('.primary').includes('background: var(--accent)'), 'головна дія екрана залита акцентом')
ok(block('.item-photo').includes('object-fit: contain'), 'фото в картці не обрізається')

console.log('\n--- сторінка товару ---')
ok(!product.includes('product-photo-glow') && !product.includes('product-lead'),
   'без декоративного світіння й рекламного абзацу')
ok(product.includes('className="primary"'), 'головна дія сторінки — .primary')
// Базовий .price стоїть нижче в каскаді; без специфічнішого селектора
// головна ціна сторінки ставала дрібнішою за назву.
ok(css.includes('.product-price-row .product-price-main {'), 'головна ціна не перебивається базовим .price')

console.log('\n--- екран переходу з legacy-host ---')
ok(main.includes('StorefrontPreparing') && main.includes('гноми налаштовують вітрину'),
   'перехід має окремий пояснювальний екран')
ok(main.includes('prepare-progress'), 'є видимий прогрес')
ok(css.includes('animation: prepare-fill 4s'), 'прогрес синхронізований із 4 с очікування')
ok(css.includes('.prepare-workshop'), 'анімована майстерня на місці')
const gate = catalog.slice(catalog.indexOf('export function AgeGate'), catalog.indexOf('function plural'))
ok(!gate.includes('sort ===') && !gate.includes('setInStock'),
   'AgeGate не звертається до стану каталогу')

console.log('\n--- доступність ---')
ok(css.includes('@media (prefers-reduced-motion: reduce)'), 'анімації поважають reduced motion')
ok(css.includes(':focus-visible'), 'фокус із клавіатури видно')

console.log(`\nДИЗАЙН ВІТРИНИ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad === 0 ? 0 : 1)
