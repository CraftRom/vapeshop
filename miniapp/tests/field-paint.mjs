/** ПОЛЕ МАЛЮЄ САМЕ: значення показує блок, а не поле.
 *
 * Причина в fields.jsx. Коротко: діагностика на живому телефоні
 * показала правильні кольори, правильну розмітку й каретку на своєму
 * місці — і при цьому гліфів у полі немає, тоді як той самий рядок у
 * звичайному блоці поруч читається. Виправляти в стилях не було чого,
 * тому значення малює блок.
 *
 * Тут перевіряється те, що робить це рішення робочим, а не красивим.
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
const css = readFileSync('src/styles.css', 'utf8')
const form = readFileSync('src/screens/Checkout.jsx', 'utf8')
const rule = (selector) => {
  const at = css.indexOf(selector)
  return at < 0 ? '' : css.slice(at, css.indexOf('}', at))
}

console.log('\n--- поле лишається робочим ---')
const ghost = rule('.input.ghost {')
ok(ghost.includes('caret-color: var(--tg-text)'),
   'каретку видно: без неї незрозуміло, куди друкувати')
ok(ghost.includes('-webkit-text-fill-color: transparent'),
   'свій текст поле не малює — інакше літери двоїлися б')
ok(rule('.input.ghost::placeholder').includes('--tg-hint'),
   'підказку малює поле: доки значення немає, блоку малювати нічого')

console.log('\n--- блок збігається з полем ---')
const echo = rule('.echo {')
for (const prop of ['padding: 11px 13px', 'font-size: 16px', 'line-height: 1.35']) {
  ok(echo.includes(prop), `ті самі метрики: ${prop}`)
}
ok(echo.includes('pointer-events: none'), 'дотики проходять крізь блок до поля')
ok(echo.includes('white-space: pre'), 'пробіли зберігаються, рядок не переноситься')
ok(rule('.echo-multiline').includes('pre-wrap'), 'коментар переноситься по словах')

console.log('\n--- довгий рядок ---')
ok(src.includes('layer.scrollLeft = input.scrollLeft'),
   'блок їде разом із полем: інакше видно початок, коли набирають кінець')
ok(src.includes("addEventListener('scroll'") && src.includes("addEventListener('input'"),
   'прокрутка стежиться і за гортанням, і за набором')

console.log('\n--- форма користується цим скрізь ---')
ok(!/<input[^>]*className=\{?["`]?input/.test(form),
   'у формі не лишилось полів, які малюють себе самі')
ok(!form.includes('<textarea'), 'коментар теж через спільний компонент')
ok((form.match(/<Field/g) || []).length >= 8, 'усі поля форми', (form.match(/<Field/g) || []).length)

console.log(`\nПОЛЕ МАЛЮЄ САМЕ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad === 0 ? 0 : 1)
