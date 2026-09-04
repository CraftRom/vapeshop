/** Сторож полів введення: міряє результат, а не вгадує причину.
 *
 * Історія цього файлу — п'ять невдалих здогадок. Текст у полі, куди
 * щойно стали, невидимий; варто перейти в сусіднє — у попередньому він
 * зʼявляється. Лікували кольором у CSS, потім `!important`, потім
 * шарами компонування, потім прокруткою з-під клавіатури. Не допомогло
 * нічого, і це саме по собі показове: кожна правка виправляла свою
 * гіпотезу про причину, а причина була інша.
 *
 * Тому тут інший підхід. Ми не намагаємось перекрити чужі стилі й не
 * вгадуємо, звідки вони беруться. Ми питаємо браузер, якого кольору
 * текст вийшов **насправді**, і якщо він зливається з підкладкою —
 * ставимо свій колір просто на елемент. Хто саме зробив текст
 * невидимим — тема Telegram, стилі WebView чи автозаповнення — стає
 * неважливо: перевіряється наслідок.
 *
 * Спрацьовує лише тоді, коли справді зле. Якщо кольори нормальні,
 * сторож нічого не чіпає.
 */

/** Поріг злиття. 0 — той самий колір, 1 — чорне з білим.
 *  0.18 приблизно відповідає межі, за якою текст ще читається на око. */
const MERGED = 0.18

/** Кольори від getComputedStyle приходять як rgb()/rgba(). */
function parse(value) {
  const parts = String(value || '').match(/[\d.]+/g)
  if (!parts || parts.length < 3) return null
  const [r, g, b, a = 1] = parts.map(Number)
  return { r, g, b, a }
}

function luminance({ r, g, b }) {
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
}

/** Підкладка самого поля може бути прозорою — тоді колір дає предок. */
function backgroundOf(node) {
  let current = node
  while (current && current !== document.documentElement) {
    const found = parse(getComputedStyle(current).backgroundColor)
    if (found && found.a > 0) return found
    current = current.parentElement
  }
  return { r: 255, g: 255, b: 255, a: 1 }
}

/** Чорний або білий — той, що на цій підкладці помітніший. */
function readableOn(background) {
  return luminance(background) > 0.5 ? '#101014' : '#ffffff'
}

/** Одна перевірка одного поля. */
export function enforceReadable(node) {
  if (!node || !node.style) return false

  // Перед заміром знімаємо свій попередній припис: інакше ми міряли б
  // власну роботу й ніколи не помітили б, що вона вже не потрібна.
  for (const prop of ['color', '-webkit-text-fill-color', 'caret-color']) {
    if (node.style.getPropertyPriority(prop) === 'important') {
      node.style.removeProperty(prop)
    }
  }

  const style = getComputedStyle(node)
  const text = parse(style.webkitTextFillColor || style.color)
  if (!text) return false

  // Повністю прозорий текст — окремий випадок того ж лиха.
  const background = backgroundOf(node)
  const merged = text.a < 0.5
    || Math.abs(luminance(text) - luminance(background)) < MERGED

  lastReport.at = Date.now()
  lastReport.text = style.webkitTextFillColor || style.color
  lastReport.background = `${style.backgroundColor} → ${JSON.stringify(background)}`
  lastReport.acted = merged

  if (!merged) return false

  const safe = readableOn(background)
  // Просто на елементі й з найвищим пріоритетом: це єдине місце, куди
  // не дотягнеться жоден зовнішній стиль, крім такого ж припису — а
  // свій ми ставимо наново на кожному натисканні клавіші.
  node.style.setProperty('color', safe, 'important')
  node.style.setProperty('-webkit-text-fill-color', safe, 'important')
  node.style.setProperty('caret-color', safe, 'important')
  // Підкладку теж закріплюємо: якщо колір тексту вже підмінили ззовні,
  // фон наступним кроком підмінять так само, і ми знову опинимось із
  // текстом кольору тла.
  node.style.setProperty(
    'background-color',
    luminance(background) > 0.5 ? '#ffffff' : '#1f1c2b',
    'important',
  )
  return true
}

/** Останній замір — для екрана діагностики.
 *
 * Сторож працює мовчки, і коли він не допомагає, незрозуміло навіть, чи
 * він узагалі щось побачив. Тут лежить те, що він виміряв востаннє:
 * без цього кожна наступна спроба знову була б здогадкою.
 */
export const lastReport = { at: 0, text: '', background: '', acted: false }

const EDITABLE = new Set(['INPUT', 'TEXTAREA'])

/** Вішає сторожа на всю сторінку. Повертає функцію зняття. */
export function watchFields() {
  const check = (node) => {
    if (!EDITABLE.has(node?.tagName)) return
    // Через кадр: стилі, які накидає оточення на активне поле,
    // зʼявляються не в ту саму мить, що й подія фокуса.
    requestAnimationFrame(() => enforceReadable(node))
  }

  const onFocus = (e) => check(e.target)
  // На кожному введеному символі теж: якщо чужий стиль зʼявляється не
  // при фокусі, а під час набору, одноразової перевірки не досить.
  const onInput = (e) => check(e.target)

  document.addEventListener('focusin', onFocus)
  document.addEventListener('input', onInput)
  return () => {
    document.removeEventListener('focusin', onFocus)
    document.removeEventListener('input', onInput)
  }
}
