import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { useFilters } from '../components/useFilters'

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

// Підписи полів. Голе «durationMs» чи «actorRole» читає той, хто писав
// код; журнал же відкривають саме тоді, коли треба швидко зрозуміти
// чуже. Полів, яких тут немає, це не приховує — вони показуються як є.
const FIELD_LABELS = {
  actor: 'Хто', login: 'Логін', ip: 'Адреса', role: 'Роль',
  path: 'Шлях', method: 'Метод', status: 'Відповідь',
  durationMs: 'Тривалість, мс', requestId: 'Запит',
  reason: 'Причина', detail: 'Що це означає', severity: 'Критичність',
  userAgent: 'Застосунок', referer: 'Звідки', event: 'Код події',
  actorRole: 'Роль того, хто діяв', query: 'Параметри',
}

const SEVERITY_CHIP = { alarm: 'error', notice: 'warn', info: '' }

function Record({ record }) {
  const [open, setOpen] = useState(false)
  // Для подій безпеки показуємо їхню критичність, а не рівень журналу:
  // невдалий вхід пишеться як info, але за змістом це не «довідково».
  const severity = record.severity
  const chip = severity
    ? (SEVERITY_CHIP[severity] ?? '')
    : (LEVEL_CHIP[record.level] ?? '')
  const badge = severity
    ? ({ alarm: 'тривога', notice: 'увага', info: 'довідка' }[severity] || severity)
    : record.level

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
        <td><span className={`chip ${chip}`}>{badge}</span></td>
        <td style={{ maxWidth: 480 }}>
          <div>{record.message}</div>
          {/* Для подій безпеки другим рядком іде пояснення, а не код:
              «Пароль не підійшов» замість «security.login.failed». Код
              лишається в розгортці — він потрібен для фільтра, не для
              читання. */}
          {record.detail
            ? <div className="faint">{record.detail}</div>
            : record.event && <div className="faint">{record.event}</div>}
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
                  <span className="faint">{FIELD_LABELS[key] || key}: </span>
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

/** Байти людською мовою. Кілобайти на десятках мегабайтів не читаються. */
function mb(bytes) {
  const value = Number(bytes || 0)
  if (value < 1024) return `${value} Б`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} КБ`
  return `${(value / (1024 * 1024)).toFixed(1)} МБ`
}

// Групи подій безпеки. Сервер зіставляє фільтр і за префіксом, тож
// «security.login» знаходить і вдалі входи, і невдалі, і блокування —
// тобто всю історію входу одним пунктом. Без цього довелося б клацати
// три різні події поспіль, щоб зрозуміти одну ситуацію.
const SECURITY_GROUPS = [
  { prefix: 'security.login', title: 'Входи в панель' },
  { prefix: 'security.token', title: 'Перепустки' },
  { prefix: 'security.access', title: 'Спроби без прав' },
  { prefix: 'security.webhook', title: 'Вебхук бота' },
  { prefix: 'security.initdata', title: 'Підписи вітрини' },
  { prefix: 'security.operator', title: 'Менеджери' },
  { prefix: 'security.settings', title: 'Налаштування' },
  { prefix: 'security.backup', title: 'Резервні копії' },
]

const SEVERITY_LABELS = {
  info: 'Довідково',
  notice: 'Варте уваги',
  alarm: 'Тривога',
}

export default function Logs() {
  // Тут це важить найбільше: розбір інциденту — це десятки уточнень
  // відбору, і посиланням на конкретну вибірку зручно ділитися.
  const [
    { service, level, event, search, severity, limit, since, until },
    setFilter,
  ] = useFilters({
    service: 'api', level: '', event: '', search: '',
    severity: '', limit: 200, since: '', until: '',
  })
  const setService = (v) => setFilter('service', v)
  const setLevel = (v) => setFilter('level', v)
  const setEvent = (v) => setFilter('event', v)
  const setSearch = (v) => setFilter('search', v)
  const setSeverity = (v) => setFilter('severity', v)
  const setLimit = (v) => setFilter('limit', v)
  const setSince = (v) => setFilter('since', v)
  const setUntil = (v) => setFilter('until', v)
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
      const result = await api.logs.read({
        service, level, event, search, severity, limit, since, until,
      })
      setData(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [service, level, event, search, severity, limit, since, until])

  useEffect(() => {
    api.logs.services().then(setMeta).catch((err) => setError(err.message))
  }, [])

  const [catalog, setCatalog] = useState([])
  const previousService = useRef(null)

  useEffect(() => {
    api.logs.events(service)
      .then((r) => {
        setEvents(r.events || [])
        // Для журналу безпеки беремо весь каталог, а не лише те, що вже
        // трапилось: подію, якої ще не було, інакше неможливо ані знайти,
        // ані навіть дізнатися, що система її вміє помічати.
        setCatalog(r.catalog || [])
      })
      .catch(() => { setEvents([]); setCatalog([]) })

    // Скидаємо відбір лише коли сервіс справді змінили. На першому
    // рендері цей ефект теж виконується — і без перевірки він стирав би
    // фільтри з відкритого посилання: колега надсилає «журнал безпеки,
    // невдалі входи за вчора», а одержувач бачить усі записи підряд.
    if (previousService.current !== null && previousService.current !== service) {
      setEvent('')
      setSeverity('')
    }
    previousService.current = service
  }, [service])

  // Підпис події людською мовою. Голий код нічого не каже тому, хто його
  // не писав, а дивиться в журнал найчастіше саме така людина.
  const titles = useMemo(() => {
    const map = {}
    for (const item of catalog) map[item.event] = item
    for (const item of events) if (item.title) map[item.event] = item
    return map
  }, [catalog, events])

  const label = (code) => titles[code]?.title || code

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

      {/* Скільки місця журнали займають і скільки їм відведено. Друге
          важливіше за перше: воно каже, що диск не заповниться. Розмір
          рахується разом із прокрученими файлами — раніше показувався
          лише поточний, і виходило «2 МБ» там, де насправді шістдесят. */}
      {meta?.usage && (
        <p className="faint" style={{ marginTop: -4, fontSize: 13 }}>
          Журнали займають <b>{mb(meta.usage.totalBytes)}</b>{' '}
          з {mb(meta.usage.budgetBytes)} відведених.{' '}
          Файл прокручується на {mb(meta.usage.maxBytesPerFile)},
          зберігається {meta.usage.backupCount} попередніх — понад цю межу
          журнали не виростуть.
        </p>
      )}

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

          {service === 'security' && (
            <label>
              <div className="faint">Критичність і вище</div>
              <select
                className="input"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
              >
                <option value="">Усі</option>
                {Object.entries(SEVERITY_LABELS).map(([key, text]) => (
                  <option key={key} value={key}>{text}</option>
                ))}
              </select>
            </label>
          )}

          <label>
            <div className="faint">Подія</div>
            <select className="input" value={event} onChange={(e) => setEvent(e.target.value)}>
              <option value="">Усі</option>
              {service === 'security' && SECURITY_GROUPS.map((g) => (
                <option key={g.prefix} value={g.prefix}>{g.title} — усе</option>
              ))}
              {events.map((e) => (
                <option key={e.event} value={e.event}>
                  {label(e.event)} ({e.count})
                </option>
              ))}
              {/* Події з каталогу, яких ще не траплялося: без них
                  неможливо перевірити, чи щось не сталося. */}
              {catalog
                .filter((c) => !events.some((e) => e.event === c.event))
                .map((c) => (
                  <option key={c.event} value={c.event}>{c.title} (0)</option>
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
            <button
              className="btn ghost"
              onClick={() => api.logs
                .download({ service, level, event, search, severity, limit, since, until })
                .catch((e) => setError(e.message))}
              title="Ті самі фільтри й та сама кількість, що на екрані"
            >
              Скачати показане
            </button>
            <button
              className="btn ghost small"
              onClick={() => api.logs
                .download({ service, full: true })
                .catch((e) => setError(e.message))}
              title="Файл цілком, без фільтрів"
            >
              Увесь файл
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
                    ? `— ${mb(data.diagnostics.sizeBytes)}` +
                      (data.diagnostics.rotatedFiles
                        ? ` (+ ${data.diagnostics.rotatedFiles} прокручених, ` +
                          `${mb(data.diagnostics.rotatedBytes)})`
                        : '') +
                      `, ${data.diagnostics.linesInTail} рядків прочитано`
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
