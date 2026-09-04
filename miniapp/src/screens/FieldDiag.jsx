/** Діагностика полів введення.
 *
 * Шість спроб полагодити невидимий у фокусі текст не дали нічого, бо
 * кожна виправляла припущення про причину. Причину не видно ні зі
 * складального середовища, ні зі знімка екрана: на знімку видно
 * наслідок, а не те, якими кольорами й стилями поле насправді
 * намальоване.
 *
 * Цей екран показує саме те, що бачить браузер на цьому телефоні:
 * обчислені кольори активного поля, наявність зовнішніх приписів і
 * перелік підключених таблиць стилів. Одного знімка звідси досить, щоб
 * замінити всі подальші здогадки на факт.
 */
import { useEffect, useRef, useState } from 'react'

import { lastReport } from '../fieldGuard'
import { APP_VERSION } from '../version'

/** Стилі, які вирішують, чи буде видно літери. */
const WATCHED = [
  ['Колір тексту', 'color'],
  ['Заливка гліфів', 'webkitTextFillColor'],
  ['Підкладка', 'backgroundColor'],
  ['Непрозорість', 'opacity'],
  ['Каретка', 'caretColor'],
  ['Розмір шрифту', 'fontSize'],
]

function Row({ label, value }) {
  return (
    <li>
      <span className="diag-key">{label}</span>
      <span className="diag-value num">{String(value)}</span>
    </li>
  )
}

export function FieldDiag() {
  const probe = useRef(null)
  const [rows, setRows] = useState(null)
  // Те, що набрали, у власному стані — щоб намалювати ті самі літери
  // звичайним текстом поруч із полем.
  const [typed, setTyped] = useState('')

  const read = () => {
    const node = probe.current
    if (!node) return
    const style = getComputedStyle(node)
    setRows({
      focused: document.activeElement === node,
      length: node.value.length,
      // Найважливіше число після довжини: якщо вміст поля прокручений
      // убік, літери просто поза видимою частиною, і жоден колір тут ні
      // до чого.
      scroll: `${node.scrollLeft} із ${node.scrollWidth} (видимо ${node.clientWidth})`,
      caretAt: `${node.selectionStart}`,
      computed: WATCHED.map(([label, prop]) => [label, style[prop] || '—']),
      // Припис просто на елементі переважає будь-яку таблицю стилів.
      // Якщо він тут не наш — його поставило оточення.
      inline: node.getAttribute('style') || 'немає',
      // Чужа таблиця стилів у переліку означає, що застосунку
      // накидають стилі ззовні, і шукати причину треба там.
      sheets: Array.from(document.styleSheets)
        .map((sheet) => (sheet.href ? sheet.href.split('/').pop() : 'вбудована'))
        .join(', ') || 'немає',
      guard: lastReport.at
        ? `${lastReport.acted ? 'втрутився' : 'не знадобився'}; `
          + `текст ${lastReport.text}, тло ${lastReport.background}`
        : 'жодного заміру ще не було',
      viewport: window.visualViewport
        ? `${Math.round(window.visualViewport.height)} із ${window.innerHeight}`
        : 'невідомо',
    })
  }

  useEffect(() => {
    read()
    // Перечитуємо постійно: стилі, які накидає оточення, зʼявляються не
    // в ту саму мить, що й фокус, і одноразовий замір їх проґавить.
    const timer = setInterval(read, 700)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <p className="card-title">Діагностика полів</p>
      <p className="hint">
        Наберіть кілька літер у полі нижче й порівняйте його з рамкою
        під ним: там ті самі символи, намальовані звичайним текстом.
        Далі — знімок екрана з показниками.
      </p>

      <div className="field">
        <label htmlFor="diag-probe">Пробне поле</label>
        <input
          id="diag-probe"
          className="input"
          ref={probe}
          onFocus={read}
          onInput={(e) => {
            setTyped(e.target.value)
            read()
          }}
          placeholder="Наберіть тут"
        />
        {/* Вирішальне порівняння: ті самі літери, намальовані звичайним
            текстом. Якщо тут вони є, а в полі вище їх немає, причина не
            в кольорі й не в стилях — не малюється саме редаговане
            поле, і лікувати треба інакше. */}
        <div className="diag-mirror">{typed || '(тут зʼявиться те саме)'}</div>
      </div>

      {rows && (
        <ul className="diag-list">
          {/* Найважливіше вгорі: на телефоні до низу довгого переліку
              просто не догортають, а знімок екрана обрізає його. */}
          <Row label="Символів у полі" value={rows.length} />
          <Row label="Каретка стоїть після символа" value={rows.caretAt} />
          <Row label="Прокрутка вмісту" value={rows.scroll} />
          <Row label="Поле у фокусі" value={rows.focused ? 'так' : 'ні'} />
          <Row label="Версія вітрини" value={APP_VERSION} />
          {rows.computed.map(([label, value]) => (
            <Row key={label} label={label} value={value} />
          ))}
          <Row label="Припис на елементі" value={rows.inline} />
          <Row label="Таблиці стилів" value={rows.sheets} />
          <Row label="Сторож" value={rows.guard} />
          <Row label="Висота вікна" value={rows.viewport} />
        </ul>
      )}
    </div>
  )
}
