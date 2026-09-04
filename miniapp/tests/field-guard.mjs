/** СТОРОЖ ПОЛІВ: чи справді він рятує невидимий текст.
 *
 * Перевіряємо логіку, а не її наявність. Підставляємо браузерні виміри
 * руками — так можна відтворити саме ту тему, у якій текст зливається з
 * підкладкою, не маючи під рукою телефона.
 */
import assert from 'node:assert'

let bad = 0
const ok = (cond, label, detail) => {
  if (cond) console.log(`  ✓ ${label}`)
  else {
    bad += 1
    console.log(`  ✗ ${label}${detail === undefined ? '' : ` — ${JSON.stringify(detail)}`}`)
  }
}

// --- підставний браузер ---------------------------------------------

const root = { tagName: 'HTML', parentElement: null }

function makeNode(paint) {
  const applied = {}
  return {
    tagName: 'INPUT',
    parentElement: root,
    paint,
    applied,
    style: {
      setProperty: (name, value, priority) => {
        applied[name] = { value, priority }
      },
      removeProperty: (name) => { delete applied[name] },
      getPropertyPriority: (name) => applied[name]?.priority || '',
    },
  }
}

globalThis.document = { documentElement: root }
globalThis.requestAnimationFrame = (fn) => fn()
globalThis.getComputedStyle = (node) => {
  if (node === root) return { backgroundColor: 'rgba(0, 0, 0, 0)' }
  // Свій припис перекриває те, що намалювало оточення — так само, як у
  // справжньому браузері.
  const forced = node.applied['-webkit-text-fill-color']?.value
  return {
    ...node.paint,
    webkitTextFillColor: forced || node.paint.webkitTextFillColor,
  }
}

const { enforceReadable } = await import('../src/fieldGuard.js')

// --- сценарії --------------------------------------------------------

console.log('\n--- усе гаразд: не чіпаємо ---')
const fine = makeNode({
  color: 'rgb(242, 240, 247)',
  webkitTextFillColor: 'rgb(242, 240, 247)',
  backgroundColor: 'rgb(31, 28, 43)',
})
ok(enforceReadable(fine) === false, 'світлий текст на темній підкладці лишається як є')
ok(Object.keys(fine.applied).length === 0, 'жодного припису не додано', fine.applied)

console.log('\n--- текст злився з підкладкою ---')
// Саме те, що описано: у полі, куди стали, гліфів не видно.
const merged = makeNode({
  color: 'rgb(33, 30, 45)',
  webkitTextFillColor: 'rgb(33, 30, 45)',
  backgroundColor: 'rgb(31, 28, 43)',
})
ok(enforceReadable(merged) === true, 'злиття помічено')
ok(merged.applied.color?.value === '#ffffff',
   'на темній підкладці ставиться світлий текст', merged.applied.color)
ok(merged.applied.color?.priority === 'important',
   'припис із найвищим пріоритетом — інакше його перекриють')
ok(merged.applied['-webkit-text-fill-color']?.value === '#ffffff',
   'заливка гліфів теж: у WebKit саме вона малює текст поля')
ok(merged.applied['caret-color']?.value === '#ffffff', 'каретку теж видно')

console.log('\n--- світла тема ---')
const light = makeNode({
  color: 'rgb(238, 238, 240)',
  webkitTextFillColor: 'rgb(238, 238, 240)',
  backgroundColor: 'rgb(245, 245, 247)',
})
ok(enforceReadable(light) === true, 'біле на білому теж злиття')
ok(light.applied.color?.value === '#101014',
   'на світлій підкладці ставиться темний текст', light.applied.color)

console.log('\n--- повністю прозорий текст ---')
const ghost = makeNode({
  color: 'rgba(242, 240, 247, 0)',
  webkitTextFillColor: 'rgba(242, 240, 247, 0)',
  backgroundColor: 'rgb(31, 28, 43)',
})
ok(enforceReadable(ghost) === true, 'прозорий текст — той самий випадок')

console.log('\n--- підкладка поля прозора ---')
// Тоді колір дає предок, інакше порівнювати не було б із чим.
const onCard = makeNode({
  color: 'rgb(30, 30, 30)',
  webkitTextFillColor: 'rgb(30, 30, 30)',
  backgroundColor: 'rgba(0, 0, 0, 0)',
})
onCard.parentElement = {
  tagName: 'DIV', parentElement: root,
  paint: { backgroundColor: 'rgb(28, 26, 38)' },
  applied: {},
}
globalThis.getComputedStyle = ((original) => (node) => {
  if (node === root) return { backgroundColor: 'rgba(0, 0, 0, 0)' }
  if (node.paint && node.tagName === 'DIV') return node.paint
  return original(node)
})(globalThis.getComputedStyle)
ok(enforceReadable(onCard) === true, 'підкладка знайдена в предків')
ok(onCard.applied.color?.value === '#ffffff', 'колір підібрано під неї',
   onCard.applied.color)

console.log('\n--- припис знімається, коли більше не потрібен ---')
// Тема змінилась на нормальну: сторож не повинен назавжди лишати свій
// колір, інакше поле перестане слухатись теми Telegram.
const healed = makeNode({
  color: 'rgb(33, 30, 45)',
  webkitTextFillColor: 'rgb(33, 30, 45)',
  backgroundColor: 'rgb(31, 28, 43)',
})
enforceReadable(healed)
assert.ok(healed.applied.color, 'припис мав зʼявитись')
healed.paint = {
  color: 'rgb(242, 240, 247)',
  webkitTextFillColor: 'rgb(242, 240, 247)',
  backgroundColor: 'rgb(31, 28, 43)',
}
ok(enforceReadable(healed) === false, 'після зміни теми втручання не потрібне')
ok(!healed.applied.color, 'свій колір знято', healed.applied)

console.log(`\nСТОРОЖ ПОЛІВ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad === 0 ? 0 : 1)
