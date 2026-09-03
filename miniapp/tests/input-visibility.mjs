// Перевіряємо, що кольори тексту у фокусі задані й нічим не перекриваються.
import { readFileSync } from 'node:fs'
const css = readFileSync('src/styles.css', 'utf8')

let bad = 0
const ok = (cond, label, extra = '') => {
  if (!cond) bad++
  console.log(`  ${cond ? '✓' : '✗'} ${label}${cond ? '' : ` — ${extra}`}`)
}

const rule = (selector) => {
  const i = css.indexOf(selector)
  if (i === -1) return ''
  return css.slice(i, css.indexOf('}', i))
}

console.log('\n--- поле у фокусі ---')
const focus = rule('.input:focus,')
ok(focus.includes('-webkit-text-fill-color'), 'заливка гліфів задана')
ok(focus.includes('!important'), 'перекриває стилі WebView')
ok(focus.includes('background'), 'фон закріплений')

console.log('\n--- поле з помилкою ---')
const badRule = rule('.input.bad,')
ok(badRule.includes('-webkit-text-fill-color'), 'текст лишається видимим')
ok(badRule.includes('warn-soft'), 'фон помилки не втрачено')

console.log('\n--- поля без класу ---')
ok(css.includes('input:focus, textarea:focus, select:focus'), 'запобіжник є')

console.log('\n--- виділення ---')
ok(css.includes('.input::selection'), 'колір виділення заданий')

console.log('\n--- жодного прозорого тексту ---')
ok(!/color:\s*transparent/.test(css), 'немає color: transparent')

console.log('\n--- підказки не рухають форму ---')
// Поломка, що повернулась: список підказок стояв у потоці просто під
// активним полем. Кожна натиснута літера рухала розмітку, а поруч
// виникав шар прокрутки — і WebView переставав перемальовувати поле у
// фокусі. Текст був на місці, каретка рухалась, гліфів не було видно
// до переходу в інше поле. Кольори тут ні до чого — вони не мінялись.
const combo = rule('.combo-list {')
ok(combo.includes('position: absolute'),
   'список підказок — накладка, а не вставка в потік')
ok(!combo.includes('-webkit-overflow-scrolling'),
   'поруч із активним полем не створюється окремий шар прокрутки')
ok(combo.includes('z-index'), 'накладка лежить над наступними полями')

console.log('\n--- під час набору немає плаваючих шарів ---')
// Поломка, що поверталась тричі. Кольори до неї непричетні: WebView
// Telegram не перемальовує растр сторінки під прибитою донизу панеллю,
// коли клавіатура міняє висоту вікна. Текст у полі є, видно його лише
// після переходу в інше поле. Лікується прибиранням причини.
ok(css.includes('body.editing .bar'),
   'панель кошика ховається, поки друкують')
ok(css.includes('body.editing .tabs'),
   'липка смуга вкладок на час набору стає звичайною')
ok(rule('.input:focus,\n.input:focus-visible {').includes('translateZ'),
   'поле у фокусі має власний шар і перемальовується незалежно')

const app = readFileSync('src/App.jsx', 'utf8')
ok(app.includes("classList.add('editing')") && app.includes('focusin'),
   'клас вішається на фокус поля')
ok(app.includes("classList.remove('editing')") && app.includes('focusout'),
   'і знімається, коли поле відпустили')

console.log(`\nПОЛЯ ВВЕДЕННЯ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
