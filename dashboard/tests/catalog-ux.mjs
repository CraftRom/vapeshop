import { readFileSync } from 'node:fs'

const catalog = readFileSync('src/pages/Catalog.jsx', 'utf8')
const css = readFileSync('src/styles.css', 'utf8')
const version = readFileSync('src/version.js', 'utf8')

/** Версія панелі не нижча за ту, де функцію випущено.
 *
 * Тут стояло точне «APP_VERSION = '1.32.1'», і набір падав на кожному
 * наступному випуску панелі, хоча з функцією все гаразд. Перевірка, що
 * падає від звичайного підняття версії, привчає не дивитись на провали.
 */
const atLeast = (source, minimum) => {
  const found = source.match(/APP_VERSION\s*=\s*'(\d+)\.(\d+)\.(\d+)'/)
  if (!found) return false
  const have = found.slice(1).map(Number)
  const need = minimum.split('.').map(Number)
  for (let i = 0; i < 3; i += 1) {
    if (have[i] !== need[i]) return have[i] > need[i]
  }
  return true
}

let bad = 0
const check = (ok, label) => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}`)
}

console.log('\n--- каталог: desktop/mobile UX ---')
check(catalog.includes('className="catalog-product"'), 'товари мають окремий адаптивний рядок/картку')
check(catalog.includes('ProductThumb product={p}'), 'у списку є фото товару з fallback')
check(catalog.includes('ProductStatus product={p}'), 'статус винесений у читабельний чіп')
check(catalog.includes('catalog-stepper'), 'залишок керується touch-friendly stepper')
check(catalog.includes("sort: 'name-asc'"), 'сортування зберігається в URL разом із фільтрами')
check(catalog.includes('paginationNumbers'), 'є клієнтська пагінація каталогу')
check(catalog.includes("productPayload(product, { is_active: true })"), 'прихований товар можна повернути в каталог')
check(catalog.includes('Дія з вибраними'), 'на ПК є групові дії для вибраних товарів')
check(css.includes('@media (max-width: 760px)') && css.includes('.catalog-product'), 'описаний мобільний breakpoint каталогу')
check(css.includes('grid-template-areas:') && css.includes('"main status"'), 'на вузькому екрані таблиця перебудовується в картки')
check(css.includes('.catalog-footer') && css.includes('position: sticky;'), 'мобільна пагінація лишається доступною внизу')
check(atLeast(version, '1.32.1'), 'каталог входить у панель від 1.32.1')

console.log(`\nКАТАЛОГ UX: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
