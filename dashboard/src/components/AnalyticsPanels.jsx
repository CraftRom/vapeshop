import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isAdmin } from '../api'
import { ErrorBar, money } from './ui'

export const sourceLabel = (source) => ({ unknown: 'Невідомо', direct: 'Прямий вхід', telegram: 'Telegram', telegram_bot: 'Telegram-бот', referral: 'Рекомендація' }[source] || source)
const num = (value) => value == null ? '—' : Number(value).toLocaleString('uk-UA', { maximumFractionDigits: 2 })
const moneyOrEmpty = (value) => value == null ? '—' : money(value)
const pct = (value) => value == null ? '—' : `${num(value)}%`
const monthLabel = (value) => new Date(`${value}-01T12:00:00Z`).toLocaleDateString('uk-UA', { month: 'long', year: 'numeric', timeZone: 'UTC' })
export function dateInZone(value, tz) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(value))
  const get = (type) => parts.find((part) => part.type === type)?.value
  return `${get('year')}-${get('month')}-${get('day')}`
}

export function AnalyticsControls({ selection, setSelection, months, timezone, busy, refresh }) {
  const change = (key, value) => setSelection({ ...selection, [key]: value })
  const currentMonth = dateInZone(Date.now(), timezone).slice(0, 7)
  return <div className="card analytics-controls">
    <div className="analytics-fields">
      <label>Історичний місяць<select aria-label="Історичний місяць" className="input" value={selection.month || ''} onChange={(e) => setSelection({ ...selection, period: 'month', month: e.target.value })}>
        <option value="">Поточний період</option>{months.map((month) => <option key={month} value={month}>{monthLabel(month)}</option>)}
      </select></label>
      <label>Порівняти з<select aria-label="Порівняти з" className="input" value={selection.compare} onChange={(e) => change('compare', e.target.value)}>
        <option value="previous">Попереднім періодом</option><option value="month">Вибраним місяцем</option><option value="none">Без порівняння</option>
      </select></label>
      {selection.compare === 'month' && <label>Місяць порівняння<select aria-label="Місяць порівняння" className="input" value={selection.compare_month || currentMonth} onChange={(e) => change('compare_month', e.target.value)}>
        {months.map((month) => <option key={month} value={month}>{monthLabel(month)}</option>)}
      </select></label>}
      <label>Графік<select aria-label="Графік" className="input" value={selection.granularity} onChange={(e) => change('granularity', e.target.value)}><option value="day">По днях</option><option value="month">По місяцях</option></select></label>
      <button className="btn ghost" disabled={busy} onClick={refresh}>{busy ? 'Оновлюємо…' : 'Оновити'}</button>
    </div>
    {selection.period === 'custom' && <div className="analytics-fields">
      <label>Від<input className="input" type="date" max={dateInZone(Date.now(), timezone)} value={selection.date_from || ''} onChange={(e) => change('date_from', e.target.value)} /></label>
      <label>До включно<input className="input" type="date" max={dateInZone(Date.now(), timezone)} value={selection.date_to || ''} onChange={(e) => change('date_to', e.target.value)} /></label>
    </div>}
    <p className="faint">Часова зона: {timezone}. Поточний місяць порівнюємо з такою самою минулою частиною попереднього; вибрані місяці — у повному доступному обсязі.</p>
  </div>
}

function Change({ value, lowerBetter = false }) {
  if (value == null) return null
  return <small className={`delta ${(lowerBetter ? value <= 0 : value >= 0) ? 'up' : 'down'}`}>{value >= 0 ? '+' : ''}{num(value)}% до порівняння</small>
}
function Kpi({ title, value, hint, change, lowerBetter }) {
  return <div className="card metric"><div className="label">{title}</div><div className="value">{value}</div><Change value={change} lowerBetter={lowerBetter} /><div className="sub">{hint}</div></div>
}

function csvCell(value) {
  let s = value == null ? '' : String(value)
  if (/^[\s]*[=+@-]/.test(s)) s = `'${s}`
  return `"${s.replaceAll('"', '""')}"`
}
function downloadCsv(rows, filename) {
  const blob = new Blob(['\uFEFF', rows.map((r) => r.map(csvCell).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function exportAnalytics(data) {
  const keys = ['sales', 'ad_sales', 'revenue', 'expected', 'orders', 'avg_check', 'new_customers', 'spend', 'cac', 'roas', 'sessions', 'converted_sessions', 'conversion']
  const names = ['Виручка продажів UAH', 'Рекламна виручка UAH', 'Отримано UAH', 'Очікуємо UAH', 'Продажі', 'Середній чек UAH', 'Нові покупці', 'Витрати UAH', 'CAC UAH', 'ROAS x', 'Відвідування', 'Конвертовані', 'Конверсія %']
  const rows = [['Період від', data.window.from, 'до (виключно)', data.window.to, 'Часова зона', data.window.timezone], ['Зріз', ...names], ['Разом', ...keys.map((k) => data.analytics.metrics[k])]]
  if (data.previous) rows.push(['Порівняння', ...keys.map((k) => data.previous.metrics[k])])
  for (const row of data.series) rows.push([row.date, ...keys.map((k) => row[k])])
  for (const row of data.analytics.sources) rows.push([`Канал: ${row.source}`, ...keys.map((k) => row[k])])
  for (const row of data.analytics.campaigns) rows.push([`Кампанія: ${row.source} / ${row.campaign || 'без мітки'}`, ...keys.map((k) => row[k])])
  downloadCsv(rows, 'elfar-analytics.csv')
}

function ChannelTable({ rows, campaigns = false }) {
  return <div className="table-wrap"><table><thead><tr><th>Джерело</th>{campaigns && <th>Кампанія</th>}<th className="num">Продажі</th><th className="num">Виручка</th><th className="num">Рекламна виручка</th><th className="num">Сер. чек</th><th className="num">Нові покупці</th><th className="num">Витрати</th><th className="num">CAC</th><th className="num">ROAS</th><th className="num">Візити</th><th className="num">Конверсія</th></tr></thead>
    <tbody>{rows.map((r) => <tr key={`${r.source}:${r.campaign || ''}`}><td>{sourceLabel(r.source)}</td>{campaigns && <td>{r.campaign || 'Без мітки'}</td>}<td className="num">{r.orders}</td><td className="num">{money(r.sales)}</td><td className="num">{money(r.ad_sales)}</td><td className="num">{moneyOrEmpty(r.avg_check)}</td><td className="num">{r.new_customers}</td><td className="num">{money(r.spend)}</td><td className="num">{moneyOrEmpty(r.cac)}</td><td className="num">{r.roas == null ? '—' : `${num(r.roas)}×`}</td><td className="num">{r.sessions}</td><td className="num">{pct(r.conversion)}</td></tr>)}</tbody>
  </table>{!rows.length && <p className="muted">За цей період даних немає.</p>}</div>
}

export function MarketingMetrics({ data }) {
  const m = data.analytics.metrics, c = data.changes
  return <>
    <div className="stats-section-title"><div><h2>Залучення й ефективність</h2><p className="faint">Рекламні витрати у гривнях; дані каналів — за міткою замовлення.</p></div><button className="btn ghost small" onClick={() => exportAnalytics(data)}>CSV статистики</button></div>
    <div className="grid k4">
      <Kpi title="CAC · усі канали" value={moneyOrEmpty(m.cac)} change={c.cac} lowerBetter hint={`${money(m.spend)} витрат / ${m.new_customers} нових покупців. Це змішаний CAC.`} />
      <Kpi title="ROAS" value={m.roas == null ? '—' : `${num(m.roas)}×`} change={c.roas} hint={`${money(m.ad_sales)} виручки каналів / кампаній із витратами. Не показник прибутку.`} />
      <Kpi title="Конверсія в замовлення" value={pct(m.conversion)} change={c.conversion} hint={`${m.converted_sessions} відвідувань із замовленням / ${m.sessions} відвідувань вітрини.`} />
      <Kpi title="Нові покупці" value={m.new_customers} change={c.new_customers} hint="Унікальні клієнти з першим успішним продажем у вибраному періоді." />
    </div>
    <div className="card"><div className="stats-section-title"><div><h2>Джерела продажів</h2><p className="faint">Відоме джерело мають {pct(data.analytics.attribution_coverage)} продажів. «Невідомо» — замовлення без збереженої атрибуції.</p></div></div>
      <ChannelTable rows={data.analytics.sources} />
      <details className="analytics-details"><summary>Кампанії</summary><ChannelTable rows={data.analytics.campaigns} campaigns /></details>
    </div>
    <div className="card analytics-quality"><h2>Якість даних і правила</h2><p>Відвідування збираються після цього оновлення тільки для авторизованої вітрини. Конверсія — оформлення, включно з пізніше скасованими замовленнями; покупка напряму в боті в її знаменник не входить. Дані до встановлення оновлення неповні.</p><p>Без витрат CAC і ROAS недоступні. Витрати за поточний день беруться повністю у внесеному обсязі. Джерело — останній непрямий вхід за 30 днів; рекламна виручка визначається за каналом або кампанією внесених витрат. Стан CRM, повернення та видалення можуть змінювати історичні підсумки.</p></div>
  </>
}

export function AnalyticsOrders({ selection, data }) {
  const [source, setSource] = useState(''), [page, setPage] = useState(0), [rows, setRows] = useState(null), [error, setError] = useState('')
  const generation = useRef(0)
  const fingerprint = JSON.stringify(selection)
  useEffect(() => { setPage(0) }, [fingerprint, source])
  useEffect(() => {
    const seq = ++generation.current
    setRows(null); setError('')
    api.stats.orderSources({ ...selection, source: source || undefined, offset: page * 25 }).then((r) => { if (seq === generation.current) setRows(r) }).catch((e) => { if (seq === generation.current) setError(e.message) })
    return () => { generation.current++ }
  }, [fingerprint, source, page, data])
  const timezone = data.window.timezone
  return <div className="card"><div className="stats-section-title"><div><h2>Джерело кожного замовлення</h2><p className="faint">Відбір за датою створення заявки. Натисніть номер, щоб відкрити картку.</p></div><label>Канал<select aria-label="Канал" className="input" value={source} onChange={(e) => setSource(e.target.value)}><option value="">Усі канали</option>{[...new Set(['unknown', ...data.analytics.sources.map((r) => r.source)])].map((s) => <option key={s} value={s}>{sourceLabel(s)}</option>)}</select></label></div>
    <ErrorBar error={error} />
    <div className="table-wrap"><table><thead><tr><th>№ / дата</th><th>Клієнт</th><th>Джерело / medium</th><th>Кампанія</th><th>Content / term</th><th>Результат</th><th className="num">Сума заявки</th><th className="num">Отримано</th></tr></thead><tbody>{rows?.items.map((r) => <tr key={r.id}><td><Link to={`/orders/${r.id}`}>#{r.id}</Link><small className="analytics-cell-note">{new Date(r.created_at).toLocaleString('uk-UA', { timeZone: timezone })}</small></td><td>{r.contact_name || '—'}</td><td>{sourceLabel(r.attribution.source)}<small className="analytics-cell-note">{r.attribution.medium || '—'}</small></td><td>{r.attribution.campaign || '—'}</td><td>{r.attribution.content || '—'} / {r.attribution.term || '—'}</td><td>{{ sale: 'Продаж', refusal: 'Відмова / повернення', pending: 'У роботі' }[r.business_state] || r.business_state}</td><td className="num">{money(r.total)}</td><td className="num">{money(r.revenue)}</td></tr>)}</tbody></table></div>
    {!rows && !error && <p aria-live="polite">Завантажуємо замовлення…</p>}{rows && !rows.items.length && <p className="muted">Замовлень немає.</p>}
    <div className="row-between analytics-pagination"><span>{rows ? `Усього: ${rows.total}` : ''}</span><div className="row"><button className="btn ghost small" disabled={!page || !rows} onClick={() => setPage(page - 1)}>Назад</button><span>{page + 1}</span><button className="btn ghost small" disabled={!rows || (page + 1) * 25 >= rows.total} onClick={() => setPage(page + 1)}>Далі</button></div></div>
  </div>
}

export function SpendEditor({ selection, timezone, onSaved }) {
  const [rows, setRows] = useState([]), [error, setError] = useState(''), [busy, setBusy] = useState(false), [revision, setRevision] = useState(0)
  const [form, setForm] = useState({ day: dateInZone(Date.now(), timezone), source: '', campaign: '', amount: '' })
  const [notice, setNotice] = useState('')
  const fingerprint = JSON.stringify(selection)
  useEffect(() => {
    let active = true
    api.stats.spend(selection).then((r) => { if (active) setRows(r) }).catch((e) => { if (active) setError(e.message) })
    return () => { active = false }
  }, [fingerprint, revision])
  const refresh = () => { setRevision((r) => r + 1); onSaved() }
  const save = async (e) => {
    e.preventDefault(); setBusy(true); setError(''); setNotice('')
    try { await api.stats.saveSpend({ ...form, amount: form.amount }); setNotice('Збережено. Підсумки оновлюються.'); refresh() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const remove = async (id) => {
    setBusy(true); setError('')
    try { await api.stats.removeSpend(id); refresh() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <details className="card analytics-details"><summary>Рекламні витрати · {rows.length} записів за період</summary><p className="faint">Один підсумок за дату + source + campaign. Повторне збереження замінює суму. Source і campaign мають збігатися з UTM-мітками. Усі суми в UAH.</p><ErrorBar error={error} />
    {isAdmin() && <form className="analytics-fields" onSubmit={save}>
      <label>Дата<input className="input" type="date" min="1970-01-01" max={dateInZone(Date.now(), timezone)} required value={form.day} onChange={(e) => setForm({ ...form, day: e.target.value })} /></label>
      <label>Source<input className="input" required maxLength={80} placeholder="google / facebook" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} /></label>
      <label>Campaign<input className="input" maxLength={160} placeholder="Назва UTM-кампанії" value={form.campaign} onChange={(e) => setForm({ ...form, campaign: e.target.value })} /></label>
      <label>Витрати, грн<input className="input" type="number" min="0" max="9999999999.99" step="0.01" required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></label>
      <button className="btn" disabled={busy}>Зберегти</button>
    </form>}
    {notice && <p role="status">{notice}</p>}
    <div className="table-wrap"><table><thead><tr><th>Дата</th><th>Джерело</th><th>Кампанія</th><th className="num">Витрати</th>{isAdmin() && <th>Дії</th>}</tr></thead><tbody>{rows.map((r) => <tr key={r.id}><td>{r.day}</td><td>{r.source}</td><td>{r.campaign || '—'}</td><td className="num">{money(r.amount)}</td>{isAdmin() && <td><div className="row"><button className="btn ghost small" disabled={busy} onClick={() => { setForm({ day: r.day, source: r.source, campaign: r.campaign, amount: String(r.amount) }); setNotice('Редагуєте вибраний запис. Збереження замінить суму.') }}>Змінити</button><button className="btn ghost small" disabled={busy} onClick={() => remove(r.id)}>Видалити</button></div></td>}</tr>)}</tbody></table></div>
  </details>
}
