import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'

const SERVICE_LABEL = {
  api: 'Сайт і панель',
  bot: 'Бот',
  scheduler: 'Планувальник',
}

const LEVEL_CHIP = {
  debug: '',
  info: '',
  warning: 'warn',
  error: 'bad',
  critical: 'bad',
}

/** Час у вигляді, придатному для читання поруч із сусідніми записами.
 *
 * Дата тут зайва: у журналі дивляться останні хвилини, і повний ISO-рядок
 * лише з'їдає ширину рядка, яка потрібна повідомленню.
 */
function shortTime(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleTimeString('uk-UA', { hour12: false }) +
    '.' + String(d.getMilliseconds()).padStart(3, '0')
}

function fullDate(value) {
  if (!value) return ''
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('uk-UA')
}

/** Поля, які показуємо окремими колонками. Решта йде в розгортку. */
const SUMMARY_FIELDS = ['method', 'path', 'status', 'durationMs', 'ip']

function Record({ record }) {
  const [open, setOpen] = useState(false)
  const chip = LEVEL_CHIP[record.level] ?? ''

  const extras = Object.entries(record).filter(
    ([key]) => !['time', 'level', 'service', 'logger', 'message'].includes(key),
  )

  return (
    <>
      <tr
        onClick={() => setOpen((v) => !v)}
        style={{ cursor: 'pointer' }}
        title={fullDate(record.time)}
      >
        <td className="faint" style={{ whiteSpace: 'nowrap' }}>{shortTime(record.time)}</td>
        <td><span className={`chip ${chip}`}>{record.level}</span></td>
        <td style={{ maxWidth: 480 }}>
          <div>{record.message}</div>
          {record.event && <div className="faint">{record.event}</div>}
        </td>
        <td className="faint" style={{ whiteSpace: 'nowrap' }}>
          {SUMMARY_FIELDS.filter((f) => record[f] !== undefined)
            .map((f) => `${record[f]}`)
            .join(' · ')}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={4}>
            {/* Повний запис як є. Саме він потрібен, коли фільтри вже
                звузили вибірку до кількох рядків і треба зрозуміти деталі. */}
            <pre
              style={{
                margin: 0, padding: 12, overflowX: 'auto',
                background: 'rgba(0,0,0,.25)', borderRadius: 8,
                fontSize: 12, lineHeight: 1.5,
              }}
            >
              {extras.map(([key, value]) => (
                <div key={key}>
                  <span className="faint">{key}: </span>
                  {typeof value === 'string' ? value : JSON.stringify(value)}
                </div>
              ))}
            </pre>
          </td>
        </tr>
      )}
    </>
  )
}

export default function Logs() {
  const [service, setService] = useState('api')
  const [level, setLevel] = useState('')
  const [event, setEvent] = useState('')
  const [search, setSearch] = useState('')
  const [limit, setLimit] = useState(200)
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [auto, setAuto] = useState(false)

  const [meta, setMeta] = useState(null)
  const [events, setEvents] = useState([])
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const result = await api.logs.read({ service, level, event, search, limit, since, until })
      setData(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [service, level, event, search, limit, since, until])

  useEffect(() => {
    api.logs.services().then(setMeta).catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    api.logs.events(service).then((r) => setEvents(r.events)).catch(() => setEvents([]))
    setEvent('')
  }, [service])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!auto) return undefined
    // Десять секунд: частіше немає сенсу, бо журнал читають очима, а
    // кожне оновлення — це читання двох мегабайтів з диска.
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [auto, load])

  return (
    <div>
      <h1>Журнал</h1>
      <p className="faint" style={{ marginTop: -8 }}>
        Останні записи з файлів журналу. Натисніть рядок, щоб побачити всі поля.
      </p>

      {error && <div className="card error" style={{ marginBottom: 14 }}>{error}</div>}

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="grid k3">
          <label>
            <div className="faint">Сервіс</div>
            <select className="input" value={service} onChange={(e) => setService(e.target.value)}>
              {(meta?.services || [{ service: 'api' }]).map((s) => (
                <option key={s.service} value={s.service}>
                  {SERVICE_LABEL[s.service] || s.service}
                  {s.exists === false ? ' — порожньо' : ''}
                </option>
              ))}
            </select>
          </label>

          <label>
            <div className="faint">Рівень і вище</div>
            <select className="input" value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="">Усі</option>
              {(meta?.levels || []).map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </label>

          <label>
            <div className="faint">Подія</div>
            <select className="input" value={event} onChange={(e) => setEvent(e.target.value)}>
              <option value="">Усі</option>
              {events.map((e) => (
                <option key={e.event} value={e.event}>{e.event} ({e.count})</option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid k3" style={{ marginTop: 12 }}>
          <label>
            <div className="faint">Пошук у будь-якому полі</div>
            <input
              className="input"
              value={search}
              placeholder="IP, шлях, логін, requestId…"
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && load()}
            />
          </label>

          <label>
            <div className="faint">Від дати</div>
            <input
              className="input"
              type="date"
              value={since}
              onChange={(e) => setSince(e.target.value)}
            />
          </label>

          <label>
            <div className="faint">До дати включно</div>
            <input
              className="input"
              type="date"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </label>
        </div>

        <div className="grid k3" style={{ marginTop: 12 }}>
          <label>
            <div className="faint">Скільки записів</div>
            <select className="input" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[100, 200, 500, 1000].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>

          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10 }}>
            <button className="btn" onClick={load} disabled={busy}>
              {busy ? 'Читаю…' : 'Оновити'}
            </button>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              <span className="faint">кожні 10 с</span>
            </label>
          </div>
        </div>
      </div>

      <div className="card">
        {data && (
          <p className="faint" style={{ marginTop: 0 }}>
            Показано {data.returned} із {data.scanned} переглянутих
            {data.truncated && ' — є ще, звузьте фільтр або підніміть ліміт'}
          </p>
        )}

        {data && data.records.length === 0 && (
          <div>
            <p className="faint">Порожньо. Чому саме — видно нижче.</p>
            {data.diagnostics && (
              <ul className="faint" style={{ fontSize: 13, lineHeight: 1.7 }}>
                <li>
                  Каталог журналу:{' '}
                  {data.diagnostics.logDir
                    ? <code>{data.diagnostics.logDir}</code>
                    : <b>не задано LOG_DIR — записи йдуть лише в docker logs</b>}
                </li>
                <li>
                  Файл: <code>{data.diagnostics.file}</code>{' '}
                  {data.diagnostics.exists
                    ? `— ${Math.round(data.diagnostics.sizeBytes / 1024)} КБ, ` +
                      `${data.diagnostics.linesInTail} рядків прочитано`
                    : '— не існує'}
                </li>
                <li>
                  {data.diagnostics.exists && data.diagnostics.linesInTail > 0
                    ? 'Файл читається — отже, записи відсіює фільтр. Спробуйте скинути дати й рівень.'
                    : 'Файл порожній або відсутній. Перевірте LOG_DIR у .env і те, що том змонтований у контейнер.'}
                </li>
              </ul>
            )}
          </div>
        )}

        {data && data.records.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Час</th>
                  <th>Рівень</th>
                  <th>Повідомлення</th>
                  <th>Деталі</th>
                </tr>
              </thead>
              <tbody>
                {data.records.map((r, i) => (
                  <Record key={`${r.time}-${i}`} record={r} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {meta && !meta.logDir && (
        <div className="card" style={{ marginTop: 14 }}>
          <p className="faint" style={{ margin: 0 }}>
            Файлове логування вимкнено: не задано <code>LOG_DIR</code>.
            Записи йдуть лише в <code>docker compose logs</code>.
          </p>
        </div>
      )}
    </div>
  )
}
