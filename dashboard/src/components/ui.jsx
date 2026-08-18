import { createContext, useCallback, useContext, useEffect, useState } from 'react'

// ------------------------------------------------------------------ сповіщення

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null)

  const notify = useCallback((message, kind = 'ok') => {
    setToast({ message, kind, key: Date.now() })
  }, [])

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 3200)
    return () => clearTimeout(timer)
  }, [toast])

  return (
    <ToastContext.Provider value={notify}>
      {children}
      {toast && (
        <div className={`toast ${toast.kind === 'bad' ? 'bad' : ''}`} role="status" key={toast.key}>
          {toast.message}
        </div>
      )}
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)

// ---------------------------------------------------------------------- поля

export function Field({ label, hint, children }) {
  return (
    <div className="field">
      {label && <label>{label}</label>}
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  )
}

// -------------------------------------------------------------------- модалка

export function Modal({ title, onClose, children, footer }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
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
  `${Number(value ?? 0).toLocaleString('uk-UA', { maximumFractionDigits: 0 })} ₴`

export const date = (iso) =>
  new Date(iso).toLocaleDateString('uk-UA', { day: '2-digit', month: '2-digit', year: '2-digit' })

export const dateTime = (iso) =>
  new Date(iso).toLocaleString('uk-UA', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
