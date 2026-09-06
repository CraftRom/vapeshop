/** ПОЛЯ ВВОДУ: правила, написані з нуля.
 *
 * Попередній набір стеріг нашарування із семи спроб полагодити
 * невидимий під час набору текст — дублювання кольору, перефарбування у
 * фокусі з !important, закріплення підкладки, шар компонування на
 * активному полі. Жодна з них не допомогла, а разом вони зробили поле
 * складнішим за будь-яке звичайне.
 *
 * Тепер стережемо протилежне: щоб поле лишалось простим. Кожне зайве
 * оголошення тут — це наступна спроба вгадати причину замість того, щоб
 * її виміряти.
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

const css = readFileSync('src/styles.css', 'utf8')
const rule = (selector) => {
  const at = css.indexOf(selector)
  return at < 0 ? '' : css.slice(at, css.indexOf('}', at))
}

console.log('\n--- поле має все, без чого не працює ---')
const base = rule('.input {')
ok(base.includes('color: var(--tg-text)'), 'колір тексту — з теми Telegram')
ok(base.includes('background: var(--tg-secondary-bg)'), 'підкладка — з теми')
ok(base.includes('font: inherit'), 'шрифт сторінки: поля не успадковують його самі')
ok(base.includes('font-size: 16px'),
   'не менше 16px — інакше браузер зумить сторінку при фокусі')
ok(base.includes('-webkit-appearance: none'),
   'без власного оформлення від системи: воно дає чорне на чорному')
ok(base.includes('box-sizing: border-box'), 'поле не вилазить за ширину екрана')

console.log('\n--- і нічого зайвого ---')
ok(!base.includes('-webkit-text-fill-color'),
   'колір не дублюється: одного оголошення досить')
ok(!base.includes('!important'), 'без !important')
ok(!base.includes('transform'), 'без шару компонування')
ok(!base.includes('will-change'), 'без підказок движку про перемальовування')

const focus = rule('.input:focus {')
ok(focus.includes('border-color'), 'фокус міняє рамку')
// border-color — це рамка, а не фарбування тексту, тож прибираємо її
// з розгляду перед перевіркою.
const painted = focus.replace(/border-color:[^;]*;?/g, '')
ok(!/(color|background|opacity|text-fill):/.test(painted),
   'і більше нічого: фарбування у фокусі не перераховується', painted.trim())

console.log('\n--- автозаповнення ---')
// Єдине місце, де без -webkit-text-fill-color не обійтись: браузер
// підмінює і колір, і тло власними, звичайним color це не перекрити.
const autofill = rule('input:-webkit-autofill,')
ok(autofill.includes('-webkit-text-fill-color'), 'колір гліфів закріплений')
ok(autofill.includes('box-shadow'), 'тло закріплене внутрішньою тінню')

console.log('\n--- жодного прозорого тексту ---')
ok(!/color:\s*transparent/.test(css), 'немає color: transparent')

console.log(`\nПОЛЯ ВВОДУ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad === 0 ? 0 : 1)
