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

export function FieldDiag() {
  const probe = useRef(null)
  const [rows, setRows] = useState(null)

  const read = () => {
    const node = probe.current
    if (!node) return
    const style = getComputedStyle(node)
    setRows({
      focused: document.activeElement === node,
      length: node.value.length,
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
        Станьте в поле нижче, наберіть кілька літер і надішліть знімок
        екрана розробнику. Якщо літер не видно — саме це й потрібно
        зафіксувати разом із показниками.
      </p>

      <div className="field">
        <label htmlFor="diag-probe">Пробне поле</label>
        <input
          id="diag-probe"
          className="input"
          ref={probe}
          onFocus={read}
          onInput={read}
          placeholder="Наберіть тут"
        />
      </div>

      {rows && (
        <ul className="diag-list">
          <li><span>Версія вітрини</span><span className="num">{APP_VERSION}</span></li>
          <li>
            <span>Поле у фокусі</span>
            <span>{rows.focused ? 'так' : 'ні'}</span>
          </li>
          <li><span>Символів у полі</span><span className="num">{rows.length}</span></li>
          {rows.computed.map(([label, value]) => (
            <li key={label}><span>{label}</span><span className="num">{value}</span></li>
          ))}
          <li><span>Припис на елементі</span><span className="num">{rows.inline}</span></li>
          <li><span>Таблиці стилів</span><span className="num">{rows.sheets}</span></li>
          <li><span>Сторож</span><span className="num">{rows.guard}</span></li>
          <li><span>Висота вікна</span><span className="num">{rows.viewport}</span></li>
        </ul>
      )}
    </div>
  )
}
