import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Empty, ErrorBar, Loading, Modal } from './ui'
import { api } from '../api'
import './imageField.css'

const MAX_BYTES = 8 * 1024 * 1024
const TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
const humanSize = (bytes) =>
  bytes < 1024 * 1024
    ? `${Math.ceil(bytes / 1024)} КБ`
    : `${(bytes / 1024 / 1024).toFixed(1)} МБ`

export default function ImageField({
  value,
  onChange,
  label = 'Зображення',
  hint,
  onBusyChange,
  disabled = false,
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [broken, setBroken] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [linkOpen, setLinkOpen] = useState(false)
  const fileInput = useRef(null)
  const locked = useRef(false)
  const alive = useRef(true)
  const latestChange = useRef(onChange)
  latestChange.current = onChange
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    setBroken(false)
  }, [value])
  useEffect(() => {
    onBusyChange?.(busy)
  }, [busy, onBusyChange])

  const upload = async (file) => {
    if (!file || locked.current || disabled) return
    setError('')
    if (
      !TYPES.includes(file.type) &&
      !(file.type === '' && /\.(jpe?g|png|gif|webp)$/i.test(file.name))
    ) {
      setError(
        'Виберіть JPG, PNG, WebP або GIF. Інші формати не підтримуються.',
      )
      return
    }
    if (file.size > MAX_BYTES) {
      setError('Файл більший за 8 МБ. Зменште його або виберіть інший.')
      return
    }
    locked.current = true
    setBusy(true)
    try {
      const result = await api.media.upload(file)
      if (alive.current) {
        latestChange.current(result.url)
        setLinkOpen(false)
      }
    } catch (err) {
      if (alive.current) setError(err.message)
    } finally {
      locked.current = false
      if (alive.current) setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }
  const paste = (event) => {
    const file = [...event.clipboardData.items]
      .find((item) => item.kind === 'file' && item.type.startsWith('image/'))
      ?.getAsFile()
    if (file) {
      event.preventDefault()
      upload(file)
    }
  }
  const blocked = busy || disabled

  return (
    <div
      className={`image-field ${dragging ? 'is-dragging' : ''}`}
      onPaste={paste}
      onDragOver={(e) => {
        if (!blocked) {
          e.preventDefault()
          setDragging(true)
        }
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        if (!blocked) upload(e.dataTransfer.files?.[0])
      }}
    >
      <div className="image-field-heading">
        <span id={`${id}-label`}>{label}</span>
        {value && <span className="chip info">Додано</span>}
      </div>
      <ErrorBar error={error} />
      {value ? (
        <div className="image-field-preview">
          <img
            key={value}
            src={value}
            alt="Попередній перегляд зображення"
            onError={() => setBroken(true)}
          />
          <div>
            <strong>
              {broken
                ? 'Попередній перегляд недоступний'
                : 'Зображення вибрано'}
            </strong>
            <p>{value}</p>
            {broken && (
              <small>
                Перевірте посилання або завантажте файл. Зовнішній сайт може
                блокувати перегляд.
              </small>
            )}
            <button
              type="button"
              className="btn ghost small"
              disabled={blocked}
              onClick={() => {
                setError('')
                onChange('')
              }}
            >
              Прибрати зображення
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="image-dropzone"
          disabled={blocked}
          onClick={() => fileInput.current?.click()}
        >
          <span className="image-drop-symbol" aria-hidden="true">
            ↑
          </span>
          <strong>
            {busy ? 'Завантажуємо зображення…' : 'Додати зображення'}
          </strong>
          <small>
            Перетягніть файл, вставте з буфера або натисніть для вибору
          </small>
        </button>
      )}
      <div className="image-field-actions">
        <button
          type="button"
          className="btn ghost small"
          onClick={() => fileInput.current?.click()}
          disabled={blocked}
        >
          {busy
            ? 'Завантажуємо…'
            : value
              ? 'Замінити файл'
              : 'Завантажити файл'}
        </button>
        <button
          type="button"
          className="btn ghost small"
          disabled={blocked}
          onClick={() => setOpen(true)}
        >
          Обрати зі сховища
        </button>
        <button
          type="button"
          className="btn ghost small"
          disabled={blocked}
          aria-expanded={linkOpen}
          onClick={() => setLinkOpen((v) => !v)}
        >
          За посиланням
        </button>
      </div>
      <input
        ref={fileInput}
        type="file"
        aria-label={`Завантажити: ${label}`}
        accept={TYPES.join(',')}
        hidden
        disabled={blocked}
        onChange={(e) => upload(e.target.files?.[0])}
      />
      {linkOpen && (
        <label className="image-link-input">
          <span>Пряме посилання на зображення</span>
          <input
            className="input"
            aria-label="Пряме посилання на зображення"
            type="text"
            inputMode="url"
            disabled={blocked}
            placeholder="https://example.com/photo.jpg"
            value={value || ''}
            onChange={(e) => {
              setError('')
              onChange(e.target.value.trim())
            }}
          />
          <small>
            Для зовнішнього посилання використовуйте JPG або PNG. WebP і GIF
            краще завантажити файлом.
          </small>
        </label>
      )}
      <p className="image-field-hint">
        {hint || 'JPG, PNG, WebP або GIF, до 8 МБ.'}
      </p>
      {open && (
        <ImageLibrary
          onClose={() => setOpen(false)}
          onPick={(url) => {
            setError('')
            onChange(url)
            setOpen(false)
          }}
        />
      )}
    </div>
  )
}

function ImageLibrary({ onPick, onClose }) {
  const bodyRef = useRef(null)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [revision, setRevision] = useState(0)
  const [pending, setPending] = useState(null)
  useEffect(() => {
    const dialog = bodyRef.current?.closest('[role="dialog"]')
    if (dialog && !dialog.contains(document.activeElement))
      dialog.focus({ preventScroll: true })
  }, [data, error])
  useEffect(() => {
    let alive = true
    setError('')
    setData(null)
    const timer = setTimeout(
      () =>
        api.media
          .list({ search, offset: page * 24, limit: 24 })
          .then((result) => {
            if (alive) setData(result)
          })
          .catch((err) => {
            if (alive) setError(err.message)
          }),
      search ? 200 : 0,
    )
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [search, page, revision])
  const remove = async (name) => {
    if (pending || !window.confirm(`Видалити файл «${name}» зі сховища?`))
      return
    setPending(name)
    setError('')
    try {
      await api.media.remove(name)
      setRevision((v) => v + 1)
    } catch (err) {
      setError(err.message)
    } finally {
      setPending(null)
    }
  }
  return createPortal(
    <Modal
      title="Сховище зображень"
      className="image-library-modal"
      onClose={onClose}
      footer={
        <>
          <span className="muted">Знайдено: {data?.total ?? '…'}</span>
          <button
            type="button"
            className="btn ghost small"
            disabled={!page}
            onClick={() => setPage((v) => v - 1)}
          >
            Попередня
          </button>
          <button
            type="button"
            className="btn ghost small"
            disabled={!data?.has_more}
            onClick={() => setPage((v) => v + 1)}
          >
            Наступна
          </button>
        </>
      }
    >
      <div className="image-library-body" ref={bodyRef}>
        <input
          className="input"
          type="search"
          aria-label="Пошук зображень"
          placeholder="Пошук у всьому сховищі…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(0)
          }}
        />
        <ErrorBar error={error} />
        {error && (
          <button
            type="button"
            className="btn ghost small"
            onClick={() => setRevision((v) => v + 1)}
          >
            Повторити завантаження
          </button>
        )}
        {!data && !error ? (
          <Loading rows={3} />
        ) : (
          data && (
            <>
              <p className="muted">
                У сховищі: {data.storedTotal ?? data.total} ·{' '}
                {humanSize(data.totalBytes || 0)}
              </p>
              {!data.files.length ? (
                <Empty title="Зображень немає">
                  Змініть пошук або завантажте новий файл.
                </Empty>
              ) : (
                <div className="image-library-grid">
                  {data.files.map((file) => (
                    <article key={file.name}>
                      <button
                        type="button"
                        className="image-library-pick"
                        onClick={() => onPick(file.url)}
                        aria-label={`Вибрати ${file.name}`}
                      >
                        <img src={file.url} alt="" loading="lazy" />
                        <span>{file.name}</span>
                      </button>
                      <div>
                        <small>{humanSize(file.sizeBytes)}</small>
                        <button
                          type="button"
                          className="btn danger small"
                          disabled={pending !== null}
                          onClick={() => remove(file.name)}
                        >
                          Видалити
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </>
          )
        )}
      </div>
    </Modal>,
    document.body,
  )
}
