import { useEffect, useRef, useState } from 'react'
import { api, isAdmin } from '../api'
import { ErrorBar, Modal } from './ui'
import { dateInZone } from './AnalyticsPanels'

export function ClosedPeriods({ timezone, selected, onOpen, snapshot }) {
  const [rows, setRows] = useState([]), [error, setError] = useState('')
  const [loading, setLoading] = useState(true), [revision, setRevision] = useState(0)
  const [month, setMonth] = useState(''), [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState('')
  const sending = useRef(false), mounted = useRef(true)
  const current = dateInZone(Date.now(), timezone).slice(0, 7)
  const last = new Date(`${current}-01T12:00:00Z`)
  last.setUTCMonth(last.getUTCMonth() - 1)
  const max = last.toISOString().slice(0, 7)
  const target = month || max
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    let active = true
    setLoading(true);setError('')
    api.stats.closedPeriods().then(value => { if (active) setRows(value.items || []) })
      .catch(e => { if (active) setError(e.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [revision])
  const close = async () => {
    if (sending.current || !confirm) return
    sending.current = true;setBusy(true);setError('');setNotice('')
    const closing = confirm
    try {
      await api.stats.closePeriod(closing)
      if (mounted.current) { setNotice(closing);setConfirm('');setRevision(v => v + 1) }
    } catch(e) { if (mounted.current) setError(e.message) }
    finally { sending.current = false;if (mounted.current) setBusy(false) }
  }
  return <section className="card closed-periods" aria-label="Збережені місячні звіти">
    <h2>Збережені місячні звіти</h2>
    <p className="faint">Зафіксуйте завершений місяць, щоб його підсумки не змінювались після оновлень CRM або рекламних витрат. Поточні замовлення й витрати залишаються доступними для роботи.</p>
    <ErrorBar error={error} />
    {error && <button className="btn ghost small" onClick={() => setRevision(v => v + 1)}>Оновити список звітів</button>}
    <div className="analytics-fields">
      <label>Перегляд звіту<select className="input" aria-label="Перегляд звіту" value={selected || ''} disabled={busy || loading} onChange={e => onOpen(e.target.value)}>
        <option value="">Поточна статистика</option>
        {selected && !rows.some(r => r.month === selected) && <option value={selected}>{selected} · збережений</option>}
        {rows.map(r => <option key={r.month} value={r.month}>{r.month} · {r.timezone}</option>)}
      </select></label>
      {isAdmin() && <>
        <label>Місяць для фіксації<input className="input" aria-label="Місяць для фіксації" type="month" min="1970-01" max={max} value={target} disabled={busy} onChange={e => setMonth(e.target.value)} /></label>
        <button className="btn ghost" disabled={busy || loading || !target || target > max || target < '1970-01' || rows.some(r => r.month === target)} onClick={() => setConfirm(target)}>Зафіксувати місяць</button>
      </>}
    </div>
    {loading && <p role="status">Завантажуємо список звітів…</p>}
    {!loading && !rows.length && !error && <p className="faint">Збережених звітів поки немає.</p>}
    {notice && <p role="status">Звіт за {notice} збережено. <button className="btn ghost small" onClick={() => onOpen(notice)}>Переглянути збережений звіт</button></p>}
    {snapshot && <div className="closed-period-notice" role="status">
      <strong>Зафіксований звіт · {snapshot.month}</strong>
      <p>Збережено {new Date(snapshot.closed_at).toLocaleString('uk-UA', { timeZone: snapshot.timezone })} ({snapshot.timezone}) · {snapshot.closed_by}.</p>
      <p>Показники й CSV відповідають моменту фіксації. Порівняння вимкнено; живий список замовлень і редактор витрат доступні у поточній статистиці.</p>
      <button className="btn ghost small" onClick={() => onOpen('')}>До поточної статистики</button>
    </div>}
    {confirm && <Modal title={`Зафіксувати ${confirm}?`} onClose={() => { if (!sending.current) setConfirm('') }} footer={<>
      <button className="btn ghost" disabled={busy} onClick={() => setConfirm('')}>Скасувати</button>
      <button className="btn" disabled={busy} onClick={close}>{busy ? 'Зберігаємо звіт…' : 'Підтвердити фіксацію'}</button>
    </>}>
      <p>Буде збережено повний звіт за {confirm} у часовій зоні {timezone}, з підсумками, графіками, каналами й менеджерами. Перед фіксацією перевірте статуси CRM та внесені витрати.</p>
      <p>Цей звіт не перезаписується. Подальші зміни джерел впливатимуть на поточну статистику. Це аналітичний знімок, а не бухгалтерський документ.</p>
      {error && <ErrorBar error={error} />}
    </Modal>}
  </section>
}
