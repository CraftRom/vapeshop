import { useCallback, useEffect, useState } from 'react'
import { api, isSysadmin } from '../api'
import { RELEASE_ID } from '../version'
import { StateBadge } from './StateBadge'

// A04: "enabled in settings" is not "running". The server derives each state
// from settings plus worker heartbeats; the panel only renders it.
export const MODULE_STATE = {
  ready: { tone: 'ok', label: 'Працює' },
  no_worker: { tone: 'bad', label: 'Немає виконавця' },
  not_configured: { tone: 'warn', label: 'Не налаштовано' },
  disabled: { tone: '', label: 'Вимкнено' },
}

export function moduleState(status) {
  return MODULE_STATE[status] || { tone: 'warn', label: 'Невідомо' }
}

export function useModuleStatus() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => {
    setError('')
    return api.system.modules().then(setReport).catch((err) => setError(err.message))
  }, [])
  useEffect(() => { load() }, [load])
  return { report, error, reload: load }
}

export function moduleByKey(report, key) {
  return (Array.isArray(report?.modules) ? report.modules : []).find((item) => item.key === key) || null
}

export default function ModuleStatus() {
  const { report, error, reload } = useModuleStatus()
  const [readiness, setReadiness] = useState(null)
  const [readinessError, setReadinessError] = useState('')
  const checkRelease = () => {
    setReadinessError('')
    api.system.readiness().then(setReadiness).catch((err) => setReadinessError(err.message))
  }
  return (
    <section className="card module-status" aria-label="Стан модулів">
      <header className="module-status-head">
        <div><h2>Стан модулів</h2><p className="muted">Перемикач у налаштуваннях не запускає сервіс. Тут видно, чи працює виконавець.</p></div>
        <button className="btn ghost small" type="button" onClick={reload}>Оновити</button>
      </header>
      {error && <p className="bad" role="alert">{error}</p>}
      {!report && !error && <p className="faint" role="status">Перевіряємо модулі…</p>}
      {report && <ul className="module-status-list">
        {/* An older or partial API answer must never take the settings page down. */}
        {(Array.isArray(report.modules) ? report.modules : []).map((item) => {
          const state = moduleState(item.status)
          return <li key={item.key}><StateBadge tone={state.tone}>{state.label}</StateBadge><div><strong>{item.title}</strong><small>{item.detail}</small></div></li>
        })}
      </ul>}
      {isSysadmin() && <div className="module-status-release">
        <button className="btn ghost small" type="button" onClick={checkRelease}>Перевірити готовність релізу</button>
        {readinessError && <p className="bad" role="alert">{readinessError}</p>}
        {readiness && <div role="status">
          <p><strong>{readiness.ready ? 'Готово до роботи' : 'Є проблеми'}</strong></p>
          <p className="muted">API: <span className="mono">{readiness.release?.id || readiness.build}</span>{readiness.release?.built_at ? ` · зібрано ${new Date(readiness.release.built_at).toLocaleString('uk-UA')}` : ''} · панель: <span className="mono">{RELEASE_ID}</span></p>
          <p className="muted">Ревізія БД: <span className="mono">{(readiness.migrations?.database || []).join(', ') || '—'}</span>, код: <span className="mono">{(readiness.migrations?.code_heads || []).join(', ') || '—'}</span></p>
          {(readiness.problems || []).length > 0 && <ul>{readiness.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>}
        </div>}
      </div>}
    </section>
  )
}
