import { readFileSync } from 'node:fs'

const catalog = readFileSync('src/pages/Catalog.jsx', 'utf8')
const css = readFileSync('src/styles.css', 'utf8')
const version = readFileSync('src/version.js', 'utf8')

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
check(version.includes("APP_VERSION = '1.31.3'"), 'каталог входить у поточну панель 1.31.3')

console.log(`\nКАТАЛОГ UX: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
