import { Children, cloneElement, createContext, isValidElement, useCallback, useContext, useEffect, useId, useRef, useState } from 'react'

import { mountDialog } from './dialog'

// ------------------------------------------------------------------ сповіщення

const ToastContext = createContext(() => {})

// UI-025: the kind decides how long a message stays and how it is announced.
// Errors stay until closed — a failed save must not vanish while the manager
// looks elsewhere — and interrupt screen readers (role="alert"). The glyph and
// the hidden prefix repeat the kind, so it is not told by colour alone.
const TOAST_KINDS = {
  ok: { className: 'ok', glyph: '✓', prefix: 'Готово', role: 'status', timeout: 3200 },
  info: { className: 'info', glyph: 'i', prefix: 'До відома', role: 'status', timeout: 4500 },
  warn: { className: 'warn', glyph: '!', prefix: 'Увага', role: 'status', timeout: 7000 },
  bad: { className: 'bad', glyph: '✕', prefix: 'Помилка', role: 'alert', timeout: 0 },
}
const TOAST_ALIASES = { success: 'ok', warning: 'warn', error: 'bad', danger: 'bad' }
export const toastKind = (kind) => TOAST_KINDS[TOAST_ALIASES[kind] || kind] ? (TOAST_ALIASES[kind] || kind) : 'ok'

export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null)
  const [paused, setPaused] = useState(false)

  const notify = useCallback((message, kind = 'ok') => {
    setToast({ message, kind: toastKind(kind), key: Date.now() })
    setPaused(false)
  }, [])

  useEffect(() => {
    if (!toast || paused) return
    const { timeout } = TOAST_KINDS[toast.kind]
    if (!timeout) return
    const timer = setTimeout(() => setToast(null), timeout)
    return () => clearTimeout(timer)
  }, [toast, paused])

  const meta = toast && TOAST_KINDS[toast.kind]
  return (
    <ToastContext.Provider value={notify}>
      {children}
      {toast && (
        <div
          className={`toast ${meta.className}`}
          role={meta.role}
          key={toast.key}
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
          onFocus={() => setPaused(true)}
          onBlur={() => setPaused(false)}
        >
          <span className="toast-glyph" aria-hidden="true">{meta.glyph}</span>
          {/* The prefix is a sibling, so the message element keeps exactly the message text. */}
          <span className="sr-only">{meta.prefix}: </span>
          <span className="toast-message">{toast.message}</span>
          <button type="button" className="toast-close" aria-label="Закрити сповіщення" onClick={() => setToast(null)}>✕</button>
        </div>
      )}
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)

// ---------------------------------------------------------------------- поля

const NATIVE_CONTROLS = new Set(['input', 'select', 'textarea'])

// Native controls reachable through plain HTML wrappers (a <div> holding the
// input and a helper button). Components and <label> wrappers are opaque:
// their own markup decides how the control is named.
// Children.forEach/map hand over the original elements (toArray would re-key
// copies), so the found control can be matched by identity in withControl.
function nativeControls(children, found = []) {
  Children.forEach(children, (child) => {
    if (!isValidElement(child) || typeof child.type !== 'string') return
    if (NATIVE_CONTROLS.has(child.type)) found.push(child)
    else if (child.type !== 'label') nativeControls(child.props.children, found)
  })
  return found
}

function withControl(children, control, props) {
  return Children.map(children, (child) => {
    if (child === control) return cloneElement(child, props)
    if (!isValidElement(child) || typeof child.type !== 'string' || !child.props.children) return child
    return cloneElement(child, undefined, withControl(child.props.children, control, props))
  })
}

// The caption must name its control for screen readers and clicking it must
// focus the control. When the field holds exactly one native control (directly
// or inside plain wrappers), Field gives it an id (keeping one the caller set)
// and points the <label> and the hint at it. Anything else — composite
// editors, nested fields, a switch wrapped in its own label — becomes a named
// group, so the caption is still announced for everything inside.
export function Field({ label, hint, children, htmlFor, id }) {
  const baseId = useId()
  const hintId = hint ? `${baseId}-hint` : undefined
  const controls = htmlFor ? [] : nativeControls(children)
  const control = controls.length === 1 ? controls[0] : null
  const controlId = htmlFor || control?.props.id || (control ? `${baseId}-control` : undefined)
  const describe = (current) => [current, hintId].filter(Boolean).join(' ') || undefined
  const content = control
    ? withControl(children, control, { id: controlId, 'aria-describedby': describe(control.props['aria-describedby']) })
    : children
  const group = label && !controlId
  return (
    <div
      className="field"
      id={id}
      role={group ? 'group' : undefined}
      aria-labelledby={group ? `${baseId}-label` : undefined}
      aria-describedby={group ? hintId : undefined}
    >
      {label && <label id={`${baseId}-label`} htmlFor={controlId}>{label}</label>}
      {content}
      {hint && <span className="hint" id={hintId}>{hint}</span>}
    </div>
  )
}

// -------------------------------------------------------------------- модалка

export function Modal({ title, onClose, children, footer, className = '' }) {
  const modalRef = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => mountDialog(modalRef.current, () => closeRef.current()), [])

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${className}`} ref={modalRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Закрити">×</button>
        </header>
        {children}
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------- стани

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  )
}

export function Loading({ rows = 5 }) {
  return (
    <div className="stack" aria-busy="true">
      {Array.from({ length: rows }, (_, i) => (
        <div className="skeleton" key={i} style={{ width: `${100 - i * 7}%` }} />
      ))}
    </div>
  )
}

export function ErrorBar({ error }) {
  if (!error) return null
  return <div className="error-bar" role="alert">{error}</div>
}

// ------------------------------------------------------------------ форматери

export const money = (value) =>
  `${Number(value ?? 0).toLocaleString('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₴`

export const date = (iso) =>
  new Date(iso).toLocaleDateString('uk-UA', { day: '2-digit', month: '2-digit', year: '2-digit' })

export const dateTime = (iso) =>
  new Date(iso).toLocaleString('uk-UA', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })

// ------------------------------------------------------- небезпечні дії

/** Підтвердження остаточного видалення: вимагає вписати назву.
 *
 * Звичайний confirm() тут замало — операція необоротна, а натиснути «ОК»
 * на автоматі надто легко. Друк назви змушує зупинитись і подивитись,
 * що саме стирається.
 */
export function confirmPurge(label, extra = '') {
  const typed = window.prompt(
    `Стерти «${label}» НАЗАВЖДИ?${extra ? ' ' + extra : ''}\n\n` +
    'Це необоротно. Щоб підтвердити, впишіть назву точно:',
  )
  if (typed === null) return false
  if (typed.trim() !== label.trim()) {
    window.alert('Назва не збіглася — нічого не видалено.')
    return false
  }
  return true
}

/** Рядок довідки: підпис зверху, значення знизу.
 *
 * Раніше все це йшло суцільним сірим текстом в один стовпчик — імʼя,
 * телефон, адреса виглядали однаково, і щоб знайти потрібне, доводилось
 * читати весь блок. Підпис над значенням дає зачепитись оком за те, що
 * шукаєш, не читаючи решти.
 */
export function Info({ label, children, copy }) {
  const notify = useToast()

  const copyValue = async () => {
    try {
      await navigator.clipboard.writeText(copy)
      notify('Скопійовано')
    } catch {
      // Буфер обміну недоступний (старий браузер, доступ заборонено).
      // Значення й так на екрані — виділити його можна руками.
      notify('Не вдалось скопіювати — виділіть текст', 'bad')
    }
  }

  return (
    <div className="info-row">
      <div className="info-head">
        <span className="info-label">{label}</span>
        {copy && (
          <button className="btn ghost small" onClick={copyValue}>
            Копіювати
          </button>
        )}
      </div>
      <div className="info-value">{children}</div>
    </div>
  )
}


// Повні підписи кроків. Доріжка й дозволені переходи живуть у StatusRail —
// дві копії тих самих таблиць уже розходились між списком і карткою.
