// Витягуємо чисті функції з Checkout.jsx і перевіряємо їх без React.
import { readFileSync } from 'node:fs'
const src = readFileSync('src/screens/Checkout.jsx', 'utf8')
const start = src.indexOf('export function normalizePhone')
// Беремо лише дві функції, а не весь блок до default: між ними є
// імпорти React, які в чистому Node не виконуються.
const end = src.indexOf("import {")
const block = src.slice(start, end).replace(/export /g, '')
const module = new Function(block + '\nreturn { normalizePhone, phoneError }')()
const { normalizePhone, phoneError } = module

let bad = 0
const eq = (got, want, label) => {
  const ok = got === want
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}${ok ? '' : ` — ${JSON.stringify(got)} замість ${JSON.stringify(want)}`}`)
}

console.log('\n--- нормалізація ---')
eq(normalizePhone('0671112233'), '+380671112233', 'з нуля')
eq(normalizePhone('380671112233'), '+380671112233', 'з коду країни')
eq(normalizePhone('+380671112233'), '+380671112233', 'уже правильний')
eq(normalizePhone('+38 (067) 111-22-33'), '+380671112233', 'з дужками й дефісами')
eq(normalizePhone('80671112233'), '+380671112233', 'зі старим форматом 8')
eq(normalizePhone('671112233'), '+380671112233', 'без префікса')
eq(normalizePhone(''), '', 'порожньо лишається порожнім')
eq(normalizePhone('+380671112233999'), '+380671112233', 'зайве відкидається')

console.log('\n--- перевірка ---')
eq(phoneError('+380671112233'), '', 'правильний — без помилки')
eq(phoneError(''), 'Вкажіть номер телефону', 'порожній')
eq(phoneError('+38067111'), 'Бракує цифр: 4', 'недобір рахується')
eq(phoneError('+380071112233'), 'Схоже на помилку в коді оператора', 'нуль у коді')
console.log(phoneError('+380671112233') === '' ? '' : '')

console.log(`\nТЕЛЕФОН: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
