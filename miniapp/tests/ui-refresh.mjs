import fs from 'node:fs'

const main = fs.readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8')
const catalog = fs.readFileSync(new URL('../src/screens/Catalog.jsx', import.meta.url), 'utf8')
const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')

let failed = false
const check = (ok, label) => {
  console.log(`${ok ? 'OK' : 'FAIL'} ${label}`)
  if (!ok) failed = true
}

console.log('\n--- UI refresh 2.9.1 ---')
check(main.includes('StorefrontPreparing'), '4-секундний legacy-перехід має окремий екран')
check(main.includes('гноми налаштовують вітрину'), 'екран переходу пояснює очікування')
check(main.includes('prepare-progress'), 'перехід має видимий прогрес')
check(css.includes('animation: prepare-fill 4s'), 'анімація прогресу синхронізована з 4 с очікуванням')
check(css.includes('.prepare-workshop'), 'під час переходу є анімована майстерня')
check(catalog.includes('className="catalog-hero"'), 'каталог має нову верхню ієрархію')
check(catalog.includes('className="rail rail-sort"'), 'сортування повернуто в каталог')
const gate = catalog.slice(catalog.indexOf('export function AgeGate'), catalog.indexOf('function plural'))
check(!gate.includes("sort ===") && !gate.includes('setInStock'), 'AgeGate більше не звертається до стану каталогу')
check(app.includes('className="store-head"'), 'основний екран має компактну шапку Mini App')
check(css.includes('REFRESH 2.9.1'), 'новий дизайн-шар присутній')
check(css.includes('@media (prefers-reduced-motion: reduce)'), 'анімації поважають reduced motion')

if (failed) process.exit(1)
console.log('\nUI REFRESH: усе витримано')
