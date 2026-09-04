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

console.log('\n--- сторож читабельності ---')
// Останній рубіж після пʼяти невдалих здогадок. Кольори в CSS,
// !important, шари компонування, прокрутка з-під клавіатури — жодна не
// допомогла, бо кожна виправляла свою гіпотезу про причину. Сторож
// нічого не вгадує: він питає браузер, якого кольору текст вийшов
// насправді, і втручається, лише коли той злився з підкладкою.
const guard = readFileSync('src/fieldGuard.js', 'utf8')
const app = readFileSync('src/App.jsx', 'utf8')
ok(guard.includes('getComputedStyle'),
   'колір міряється по факту, а не припускається')
ok(guard.includes("setProperty('color'") && guard.includes("'important'"),
   'свій колір ставиться просто на елемент — туди чужий стиль не дотягнеться')
ok(guard.includes('backgroundOf'),
   'прозора підкладка поля шукається в предків, інакше порівнювати нема з чим')
ok(guard.includes('removeProperty'),
   'перед заміром знімається попередній припис — інакше міряли б власну роботу')
ok(guard.includes("addEventListener('input'"),
   'перевірка й на кожному символі: чужий стиль може зʼявитись не при фокусі')
ok(app.includes('watchFields'), 'сторож увімкнений у застосунку')

// Прибране навмисно: клас editing міняв розмітку в мить фокуса, і саме
// через нього форма смикалась при кожному натисканні на поле.
ok(!/body\.editing\s*\.(bar|tabs)/.test(css),
   'розмітка не міняється у мить фокуса')

console.log('\n--- поле видно з-під клавіатури ---')
// Це Mini App у телефоні: клавіатура займає нижню половину екрана, а
// сторінка під неї не прокручується сама. Поле лишається під
// клавіатурою — людина друкує й не бачить ні тексту, ні поля. Тицяє в
// наступне, розмітка зміщується, і попереднє вигулькує вже заповненим.
ok(app.includes('scrollIntoView'), 'активне поле піднімається у видиму частину')
ok(app.includes('visualViewport'),
   'зміна висоти вікна від клавіатури відстежується')
ok(/setTimeout\(reveal/.test(app),
   'прокрутка чекає на анімацію клавіатури, інакше вікно ще старої висоти')

console.log(`\nПОЛЯ ВВЕДЕННЯ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
