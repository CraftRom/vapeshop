/** ПОЛЕ ВВЕДЕННЯ: React не пише в нього під час набору.
 *
 * Причина, виміряна на живому телефоні: у діагностиці пробне поле
 * показувало набране нормально, а поля форми — ні. Різниця одна:
 * пробне некероване. Керованому полю React присвоює `value` на кожному
 * перемальовуванні, а присвоєння посеред композиції Android-клавіатури
 * скидає її — і WebView лишається без тексту для показу.
 *
 * Тут перевіряється саме те правило, яке з цього випливає: своє ж
 * значення назад у поле не повертається ніколи, а зміна ззовні —
 * повертається завжди.
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

const src = readFileSync('src/fields.jsx', 'utf8')

console.log('\n--- поле некероване ---')
ok(src.includes('defaultValue'), 'значення передається як початкове, а не як кероване')
ok(!/\bvalue=\{/.test(src.replace(/defaultValue=\{[^}]*\}/g, '')),
   'атрибут value полю не задається — саме він і скидав композицію')

console.log('\n--- своє значення назад не повертається ---')
const effect = src.slice(src.indexOf('useEffect'), src.indexOf('const report'))
ok(effect.includes('if (value === mine.current) return'),
   'значення, яке щойно віддали назовні, у поле не пишеться')
ok(effect.includes('el.value = value'), 'зміна ззовні в поле пишеться')
ok(src.includes('mine.current = event.target.value'),
   'кожне введення запамʼятовується як своє')

console.log('\n--- поведінка на прикладах ---')
// Відтворюємо життєвий цикл руками: набір, вибір міста зі списку,
// скидання форми після оформлення.
const node = { value: '', tagName: 'INPUT' }
const state = { current: '' }

// Спрощена модель того самого правила, що й у компоненті.
const mine = { current: '' }
const sync = (incoming) => {
  if (incoming === mine.current) return 'не чіпали'
  mine.current = incoming
  node.value = incoming
  return 'записали'
}
const typed = (text) => {
  node.value = text
  mine.current = text
  state.current = text
}

typed('Гали')
ok(sync(state.current) === 'не чіпали', 'під час набору поле не переписується')
typed('Галицький')
ok(sync(state.current) === 'не чіпали', 'і далі не переписується')

// Вибір міста зі списку — значення прийшло ззовні.
state.current = 'м. Дніпро, Дніпропетровська обл.'
ok(sync(state.current) === 'записали', 'вибір зі списку доїжджає до поля')
ok(node.value === 'м. Дніпро, Дніпропетровська обл.', 'і саме те значення',
   node.value)

// Скидання форми після успішного замовлення.
state.current = ''
ok(sync(state.current) === 'записали', 'скидання форми очищає поле')
ok(node.value === '', 'поле справді порожнє', node.value)

console.log(`\nПОЛЕ ВВЕДЕННЯ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad === 0 ? 0 : 1)
