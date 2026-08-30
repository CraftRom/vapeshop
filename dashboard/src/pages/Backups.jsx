import { useEffect, useRef, useState } from 'react'
import { api, getToken } from '../api'

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

/** Підтвердження відновлення.
 *
 *  Просимо переписати назву файлу вручну. Кнопка «так» у діалозі
 *  натискається рефлекторно, а операція незворотна й затирає поточні дані.
 *  Переписування змушує подивитись, що саме відновлюється.
 */
function RestoreDialog({ item, onClose, onDone }) {
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const run = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await api.backups.restore(item.name, typed)
      onDone(result)
    } catch (e) {
      setError(e.message)
      setBusy(false)
    }
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true">
        <header>
          <h2>Відновити базу</h2>
          <button className="icon-btn" onClick={onClose}>×</button>
        </header>

        <p>
          Поточні дані буде замінено вмістом <b>{item.name}</b> від {when(item.createdAt)}.
          Усе, що з'явилося після цієї копії — замовлення, клієнти, повідомлення —
          зникне.
        </p>
        <p className="faint">
          Перед відновленням система сама зробить запобіжний знімок поточного
          стану, тож повернутись буде куди.
        </p>

        <label>
          <div className="faint">Введіть назву файлу для підтвердження</div>
          <input
            className="input"
            value={typed}
            placeholder={item.name}
            onChange={(e) => setTyped(e.target.value)}
          />
        </label>

        {error && <p className="error">{error}</p>}

        <footer>
          <button className="btn ghost" onClick={onClose} disabled={busy}>Скасувати</button>
          <button
            className="btn danger"
            disabled={busy || typed.trim() !== item.name}
            onClick={run}
          >
            {busy ? 'Відновлюю…' : 'Відновити'}
          </button>
        </footer>
      </div>
    </div>
  )
}

export default function Backups() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [restoring, setRestoring] = useState(null)
  const fileRef = useRef(null)

  const load = () => {
    setError('')
    api.backups.list().then(setData).catch((e) => setError(e.message))
  }

  useEffect(load, [])

  const create = async () => {
    setBusy('create')
    setError('')
    setNotice('')
    try {
      const item = await api.backups.create()
      setNotice(`Створено ${item.name} — ${sizeLabel(item.sizeBytes)}`)
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  const upload = async (file) => {
    if (!file) return
    setBusy('upload')
    setError('')
    setNotice('')
    try {
      const item = await api.backups.upload(file)
      setNotice(`Завантажено ${item.name}. Щоб застосувати — натисніть «Відновити».`)
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
        відновитись.
      </p>

      {error && <div className="card error" style={{ marginBottom: 14 }}>{error}</div>}
      {notice && <div className="card ok" style={{ marginBottom: 14 }}>{notice}</div>}

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <button className="btn" onClick={create} disabled={busy === 'create'}>
            {busy === 'create' ? 'Знімаю…' : 'Зробити копію зараз'}
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
                          Відновити
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
          Копії лежать на тому самому диску, що й база. Якщо помре диск —
          помруть разом із нею. Тримайте хоча б одну копію за межами сервера:
          скачайте її сюди або налаштуйте перенесення на інший хост.
        </p>
        <p className="faint" style={{ margin: 0 }}>
          Після відновлення перезапустіть API і бота, щоб вони перечитали дані.
        </p>
      </div>

      {restoring && (
        <RestoreDialog
          item={restoring}
          onClose={() => setRestoring(null)}
          onDone={(result) => {
            setRestoring(null)
            setNotice(
              `База відновлена з ${result.restored}. ` +
              `Стан до відновлення збережено як ${result.safetyCopy}. ${result.note}`,
            )
            load()
          }}
        />
      )}
    </div>
  )
}
