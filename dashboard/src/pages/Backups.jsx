import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Modal } from '../components/ui'

const REQUEST_KEY = 'elfar:backup:request'
const pending = (job) => job && ['queued', 'running'].includes(job.status)
const jobLabel = {queued: 'У черзі', running: 'Виконується', succeeded: 'Готово', failed: 'Помилка'}
function savedRequest() {
  try {
    const value = JSON.parse(sessionStorage.getItem(REQUEST_KEY) || 'null')
    return typeof value?.key === 'string' && /^[A-Za-z0-9_-]{16,80}$/.test(value.key) ? value : null
  } catch { return null }
}
function saveRequest(value) {
  try { value ? sessionStorage.setItem(REQUEST_KEY, JSON.stringify(value)) : sessionStorage.removeItem(REQUEST_KEY) } catch { /* server deduplicates active jobs even without browser storage */ }
}

function sizeLabel(bytes) {
  if (!bytes) return '0'
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} ГБ`
}

function when(value) {
  if (!value) return ''
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('uk-UA')
}

/** Restoration stops API/bot/scheduler and therefore runs on the server. */
function RestoreDialog({item,onClose}) {
  return <Modal title="Відновлення на сервері" onClose={onClose}>
    <p>Копія <b>{item.name}</b> від {when(item.createdAt)} замінить поточні дані магазину.</p>
    <p className="faint">Завантажте її та передайте системному адміністратору. На сервері адміністратор запускає <code>deploy/restore.sh</code>: скрипт зупиняє бот, API і планувальник, відновлює базу й накочує міграції.</p>
    <p className="faint">Кнопка у браузері не змінює базу. Цей дамп містить лише БД; зображення й ключ шифрування налаштувань зберігайте окремо.</p>
    <footer><button className="btn" onClick={onClose}>Зрозуміло</button></footer>
  </Modal>
}

export default function Backups() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [restoring, setRestoring] = useState(null)
  const fileRef = useRef(null)
  const requestRef = useRef(savedRequest())
  const [jobData, setJobData] = useState({jobs: [], worker: null})
  const [jobError, setJobError] = useState('')
  const [checking, setChecking] = useState(true)
  const completed = useRef(new Set())
  const revision = useRef(0)

  const load = useCallback(() => {
    setError('')
    api.backups.list().then(setData).catch((e) => setError(e.message))
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    let disposed = false, timer, inFlight = false
    const refresh = async () => {
      if (document.hidden || inFlight) return
      inFlight = true
      const version = revision.current
      try {
        const value = await api.backups.jobs()
        if (disposed || version !== revision.current) return
        setJobData({jobs: value.jobs || [], worker: value.worker})
        setJobError('')
        for (const job of value.jobs || []) {
          if (!pending(job) && !completed.current.has(job.id)) {
            completed.current.add(job.id)
            if (requestRef.current?.id === job.id) {
              requestRef.current = null; saveRequest(null)
            }
            if (job.status === 'succeeded') load()
          }
        }
      } catch (e) { if (!disposed) setJobError(e.message) }
      finally { inFlight = false; if (!disposed) setChecking(false) }
    }
    const tick = async () => {
      await refresh()
      if (!disposed) timer = setTimeout(tick, 2500)
    }
    tick()
    const visible = () => { if (!document.hidden) refresh() }
    document.addEventListener('visibilitychange', visible)
    return () => { disposed = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visible) }
  }, [load])

  const activeJob = jobData.jobs.find(pending)
  const create = async () => {
    setBusy('create'); setError(''); setNotice(''); setJobError('')
    if (!requestRef.current?.key) {
      requestRef.current = {key: crypto.randomUUID().replaceAll('-', '')}
      saveRequest(requestRef.current)
    }
    try {
      const job = await api.backups.create(requestRef.current.key)
      revision.current++
      if (pending(job)) {
        requestRef.current = {...requestRef.current, id: job.id}
        saveRequest(requestRef.current)
      } else { requestRef.current = null; saveRequest(null) }
      setJobData(value => ({...value, jobs: [job, ...value.jobs.filter(item => item.id !== job.id)]}))
      if (job.status === 'succeeded') load()
    } catch (e) {
      setError(`${e.message}. Повторіть перевірку запиту: його ключ збережено, нова копія повторно не створиться.`)
    } finally { setBusy('') }
  }

  const upload = async (file) => {
    if (!file) return
    if (file.size > 200 * 1024 * 1024) {
      setError('Максимум 200 МіБ через браузер. Більші копії передавайте на сервер через SSH.');
      if (fileRef.current) fileRef.current.value = ''
      return
    }
    setBusy('upload')
    setError('')
    setNotice('')
    try {
      const item = await api.backups.upload(file)
      setNotice(`Завантажено ${item.name}. Відновлення виконує системний адміністратор на сервері.`)
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy('')
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const remove = async (item) => {
    if (!window.confirm(`Стерти ${item.name}? Відновити з нього більше не вийде.`)) return
    setBusy(item.name)
    try {
      await api.backups.remove(item.name)
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  const download = (item) => {
    // Через прихований запит з токеном: файл віддається лише системному
    // адміністраторові, тож простим посиланням його не забрати.
    api.backups.download(item.name).catch((e) => setError(e.message))
  }

  return (
    <div>
      <h1>Резервні копії</h1>
      <p className="faint" style={{ marginTop: -8 }}>
        Знімки бази даних. Планувальник робить їх за розкладом із налаштувань,
        тут можна зняти позаплановий, завантажити копію з комп'ютера або
        переглянути порядок безпечного відновлення.
      </p>

      {error && <div className="card error" style={{ marginBottom: 14 }}>{error}</div>}
      {notice && <div className="card ok" style={{ marginBottom: 14 }}>{notice}</div>}

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <button className="btn" onClick={create} disabled={busy === 'create' || checking || Boolean(activeJob)}>
            {busy === 'create' ? 'Надсилаємо…' : activeJob ? 'Копія створюється' : requestRef.current?.key ? 'Перевірити запит' : 'Зробити копію зараз'}
          </button>
          <button
            className="btn ghost"
            onClick={() => fileRef.current?.click()}
            disabled={busy === 'upload'}
          >
            {busy === 'upload' ? 'Завантажую…' : 'Завантажити з комп\u2019ютера'}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".dump"
            style={{ display: 'none' }}
            onChange={(e) => upload(e.target.files?.[0])}
          />
          <button className="btn ghost" onClick={load}>Оновити</button>
        </div>

        {data && (
          <p className="faint" style={{ marginBottom: 0, marginTop: 12 }}>
            {data.total} копій, разом {sizeLabel(data.totalBytes)}.
            Вільно на диску {sizeLabel(data.freeBytes)}.
            Автоматичні зберігаються {data.retentionDays} днів.
          </p>
        )}
      </div>

      <section className="card" style={{marginBottom: 14}} aria-label="Фонові завдання">
        <h2 style={{marginTop: 0}}>Останні завдання</h2>
        <p className="faint">Завдання зберігається після закриття вкладки та перезапуску сервера. Завантаження копії з комп’ютера — до 200 МіБ.</p>
        {jobError && <p role="alert" className="bad">Не вдалося перевірити завдання: {jobError}</p>}
        {jobData.worker?.available === false && <p role="status">Виконавець не відповідає. {activeJob ? 'Запит збережено. ' : ''}Перевірте службу maintenance на сервері.</p>}
        {checking && <p className="faint">Перевіряємо стан…</p>}
        {!checking && !jobError && !jobData.jobs.length && <p className="faint">Фонових завдань ще немає.</p>}
        <div aria-live="polite" aria-atomic="false">
          {jobData.jobs.slice(0, 5).map(job => <p key={job.id}>
            <b>{jobLabel[job.status] || job.status}</b> · {when(job.created_at * 1000)}<br/>
            <span className="faint">{job.message}{job.result?.name ? ` — ${job.result.name}` : ''}</span>
          </p>)}
        </div>
      </section>

      {data?.database?.available && (
        <div className="card" style={{ marginBottom: 14 }}>
          <h2 style={{ marginTop: 0 }}>Сховище PostgreSQL</h2>
          <p className="faint" style={{ marginTop: -4 }}>
            Загальний фізичний розмір бази: <b>{sizeLabel(data.database.totalBytes)}</b>.
            Нижче — найбільші таблиці разом з індексами. Dead rows — простір,
            який PostgreSQL може повторно використати після autovacuum; це не втрачені дані.
          </p>
          <div style={{ overflowX: 'auto' }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Таблиця</th>
                  <th>Разом</th>
                  <th>Дані</th>
                  <th>Індекси</th>
                  <th>Рядків</th>
                  <th>Dead</th>
                </tr>
              </thead>
              <tbody>
                {(data.database.tables || []).map((table) => (
                  <tr key={table.name}>
                    <td><b>{table.name}</b></td>
                    <td>{sizeLabel(table.totalBytes)}</td>
                    <td className="faint">{sizeLabel(table.tableBytes)}</td>
                    <td className="faint">{sizeLabel(table.indexBytes)}</td>
                    <td className="faint">{Number(table.liveRows || 0).toLocaleString('uk-UA')}</td>
                    <td className="faint">{Number(table.deadRows || 0).toLocaleString('uk-UA')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(data.database.coldArchives || []).length > 0 && (
            <p className="faint" style={{ marginBottom: 8 }}>
              Cold-tier: {(data.database.coldArchives || []).map((item) => {
                const raw = Number(item.rawBytes || 0)
                const packed = Number(item.payloadBytes || 0)
                const ratio = raw > 0 ? Math.max(0, Math.round((1 - packed / raw) * 100)) : 0
                return `${item.kind}: ${Number(item.messages || 0).toLocaleString('uk-UA')} повідомлень / ${sizeLabel(packed)}${raw > 0 ? ` (стиснення ${ratio}%)` : ''}`
              }).join(' · ')}
            </p>
          )}
          <p className="faint" style={{ marginBottom: 0 }}>
            Старі закриті чати автоматично переходять у стиснений cold-tier,
            а оперативні сповіщення мають обмежений строк зберігання.
          </p>
        </div>
      )}

      <div className="card">
        {!data && <p className="faint">Завантаження…</p>}

        {data && data.items.length === 0 && (
          <p className="faint">
            Копій ще немає. Планувальник зробить першу за розкладом, або
            зніміть її зараз кнопкою вище.
          </p>
        )}

        {data && data.items.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Файл</th>
                  <th>Створено</th>
                  <th>Розмір</th>
                  <th>Дії</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.name}>
                    <td style={{ wordBreak: 'break-all' }}>
                      {item.name}
                      {item.manual && <div className="faint">знято вручну</div>}
                    </td>
                    <td className="faint" style={{ whiteSpace: 'nowrap' }}>{when(item.createdAt)}</td>
                    <td className="faint">{sizeLabel(item.sizeBytes)}</td>
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        <button className="btn small ghost" onClick={() => download(item)}>
                          Скачати
                        </button>
                        <button className="btn small" onClick={() => setRestoring(item)}>
                          Як відновити
                        </button>
                        <button
                          className="btn small danger"
                          disabled={busy === item.name}
                          onClick={() => remove(item)}
                        >
                          Стерти
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h2 style={{ marginTop: 0 }}>Про що варто пам'ятати</h2>
        <p className="faint" style={{ marginBottom: 8 }}>
          Ці копії містять лише БД: зображення та ключ шифрування налаштувань потрібно зберігати окремо. Копії лежать на тому самому диску, що й база. Якщо помре диск —
          помруть разом із нею. Тримайте хоча б одну копію за межами сервера:
          скачайте її сюди або налаштуйте перенесення на інший хост.
        </p>
        <p className="faint" style={{ margin: 0 }}>
          Відновлення виконується лише на сервері через <code>deploy/restore.sh</code>; браузер базу не змінює.
        </p>
      </div>

      {restoring && (
        <RestoreDialog
          item={restoring}
          onClose={() => setRestoring(null)}

        />
      )}
    </div>
  )
}
