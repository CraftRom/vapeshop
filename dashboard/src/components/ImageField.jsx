import { useEffect, useRef, useState } from 'react'
import { Modal } from './ui'
import { api } from '../api'

/** Поле зображення: завантаження на сервер, вибір із уже завантажених
 *  або посилання вручну.
 *
 *  Три способи, а не один, бо випадки різні: нову картинку треба залити,
 *  ту саму обкладинку для десятка товарів — вибрати зі сховища, а на
 *  чуже фото інколи справді потрібне зовнішнє посилання.
 */
export default function ImageField({ value, onChange, label = 'Зображення', hint }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef(null)

  const upload = async (file) => {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const result = await api.media.upload(file)
      onChange(result.url)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
      // Скидаємо поле, інакше повторний вибір того самого файлу не
      // викличе onChange — браузер вважає, що нічого не змінилось.
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <div style={{ marginBottom: 14 }}>
      <div className="faint" style={{ marginBottom: 6 }}>{label}</div>

      {value && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 10, alignItems: 'flex-start' }}>
          <img
            src={value}
            alt=""
            style={{
              // contain: у прев'ю треба бачити, що саме за картинка,
              // а обрізане по центру фото товару часто виглядає як
              // невиразна пляма й не дає її впізнати.
              width: 84, height: 84, objectFit: 'contain',
              background: 'var(--panel-2)',
              borderRadius: 10, background: 'rgba(0,0,0,.25)',
            }}
            onError={(e) => { e.currentTarget.style.opacity = 0.25 }}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="faint" style={{ wordBreak: 'break-all', fontSize: 12 }}>
              {value}
            </div>
            <button
              type="button"
              className="btn ghost small"
              style={{ marginTop: 6 }}
              onClick={() => onChange('')}
            >
              Прибрати
            </button>
          </div>
        </div>
      )}

      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="btn small"
          onClick={() => fileInput.current?.click()}
          disabled={busy}
        >
          {busy ? 'Завантажую…' : 'Завантажити файл'}
        </button>
        <button type="button" className="btn ghost small" onClick={() => setOpen(true)}>
          Обрати зі сховища
        </button>
        <input
          ref={fileInput}
          type="file"
          accept="image/jpeg,image/png,image/gif,image/webp"
          style={{ display: 'none' }}
          onChange={(e) => upload(e.target.files?.[0])}
        />
      </div>

      <input
        className="input"
        style={{ marginTop: 8 }}
        value={value || ''}
        placeholder="або вставте пряме посилання"
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <div className="faint" style={{ marginTop: 4 }}>{hint}</div>}
      {error && <div className="faint" style={{ color: 'var(--bad)', marginTop: 4 }}>{error}</div>}

      {open && (
        <Library
          onClose={() => setOpen(false)}
          onPick={(url) => { onChange(url); setOpen(false) }}
        />
      )}
    </div>
  )
}

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

function Library({ onPick, onClose }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  const load = () => api.media.list().then(setData).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const remove = async (name) => {
    // Файл може використовуватись у товарі, який зараз не відкритий.
    // Перевірити це дешево не вийде, тому просто попереджаємо прямо.
    if (!window.confirm(
      `Видалити ${name}?\n\nЯкщо це зображення вже стоїть у товарі чи розсилці, ` +
      'воно перестане показуватись.',
    )) return
    try {
      await api.media.remove(name)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const files = (data?.files || []).filter(
    (f) => !search || f.name.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    // Той самий Modal, що й на решті екранів: власна розмітка означала б
    // власні класи, власну поведінку Escape і власні відступи — тобто три
    // місця, де вікно поводитиметься не так, як усі інші в панелі.
    <Modal title="Сховище зображень" onClose={onClose}>

        {error && <div className="card error" style={{ marginBottom: 12 }}>{error}</div>}

        <input
          className="input"
          value={search}
          placeholder="Пошук за назвою"
          onChange={(e) => setSearch(e.target.value)}
          style={{ marginBottom: 12 }}
        />

        {data && (
          <p className="faint" style={{ marginTop: 0 }}>
            Файлів: {data.total} · займають {humanSize(data.totalBytes)}
          </p>
        )}

        {data && files.length === 0 && (
          <p className="faint">
            {data.total === 0
              ? 'Сховище порожнє. Завантажте перше зображення кнопкою «Завантажити файл».'
              : 'За цим запитом нічого немає.'}
          </p>
        )}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
            gap: 12,
            maxHeight: '55vh',
            overflowY: 'auto',
          }}
        >
          {files.map((f) => (
            <div key={f.name} style={{ textAlign: 'center' }}>
              <img
                src={f.url}
                alt={f.name}
                onClick={() => onPick(f.url)}
                style={{
                  width: '100%', height: 120, objectFit: 'contain',
                  background: 'var(--panel-2)',
                  borderRadius: 10, cursor: 'pointer',
                  background: 'rgba(0,0,0,.25)',
                }}
              />
              <div className="faint" style={{ fontSize: 11, wordBreak: 'break-all' }}>
                {f.name}
              </div>
              <div className="faint" style={{ fontSize: 11 }}>{humanSize(f.sizeBytes)}</div>
              <button
                type="button"
                className="btn danger small"
                style={{ marginTop: 4 }}
                onClick={() => remove(f.name)}
              >
                Видалити
              </button>
            </div>
          ))}
        </div>
    </Modal>
  )
}
