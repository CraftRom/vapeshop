import { useCallback, useEffect, useRef, useState } from 'react'
import ImageField from '../components/ImageField'
import { api } from '../api'
import {
  Empty,
  ErrorBar,
  Field,
  Loading,
  Modal,
  dateTime,
  useToast,
} from '../components/ui'
import { Pagination } from '../components/Pagination'
import { useVisiblePolling } from '../components/useVisiblePolling'
import {
  BroadcastPreviewText,
  broadcastLength,
  broadcastValidation,
  plainBroadcastText,
} from './broadcastContent'
import './broadcasts.css'

const STATUS_CHIP = {
  draft: { label: 'Чернетка', cls: '' },
  scheduled: { label: 'Заплановано', cls: 'warn' },
  sending: { label: 'Надсилається', cls: 'warn' },
  sent: { label: 'Завершено', cls: 'ok' },
  failed: { label: 'Помилка', cls: 'bad' },
}
function nextHourLocal() {
  const d = new Date()
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`
}

function BroadcastForm({ source, segments, onClose, onSaved }) {
  const notify = useToast()
  const [form, setForm] = useState({
    title: source?.title || '',
    text: source?.text || '',
    text_format: source?.text_format || (source?.id ? 'html' : 'plain'),
    photo_url: source?.photo_url || '',
    button_text: source?.button_text || '',
    button_url: source?.button_url || '',
  })
  const [segment, setSegment] = useState({
    type: 'all',
    days: 30,
    min_total: 1000,
    ...source?.segment,
  })
  const [reach, setReach] = useState(null)
  const [reachError, setReachError] = useState('')
  const [reachRevision, setReachRevision] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [imageBusy, setImageBusy] = useState(false)
  const [when, setWhen] = useState(nextHourLocal)
  const saving = useRef(false)
  const savedId = useRef(source?.id || null)
  const clientKey = useRef(crypto.randomUUID())
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  const payloadSegment = {
    type: segment.type,
    ...(segment.type === 'inactive' ? { days: Number(segment.days) } : {}),
    ...(segment.type === 'top_spenders'
      ? { min_total: String(segment.min_total) }
      : {}),
  }
  const segmentValid =
    (segment.type !== 'inactive' ||
      (Number.isInteger(Number(segment.days)) &&
        Number(segment.days) >= 1 &&
        Number(segment.days) <= 36500)) &&
    (segment.type !== 'top_spenders' ||
      (segment.min_total !== '' &&
        Number(segment.min_total) >= 0 &&
        Number.isFinite(Number(segment.min_total))))
  const segmentKey = JSON.stringify(payloadSegment)
  useEffect(() => {
    let active = true
    setReach(null)
    setReachError('')
    if (!segmentValid) {
      setReachError('Перевірте умови вибраної аудиторії.')
      return
    }
    const timer = setTimeout(
      () =>
        api.broadcasts
          .preview(JSON.parse(segmentKey))
          .then((data) => {
            if (active) setReach(data.count)
          })
          .catch((err) => {
            if (active) setReachError(err.message)
          }),
      200,
    )
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [segmentKey, segmentValid, reachRevision])
  const validation = broadcastValidation(form)
  const valid = !Object.keys(validation).length && segmentValid
  const disabled = !!busy || imageBusy
  const length = broadcastLength(form.text, form.text_format)
  const limit = form.photo_url ? 1024 : 4096
  const close = () => {
    if (!saving.current && !imageBusy) onClose()
  }
  const save = async (mode) => {
    if (saving.current || imageBusy) return
    if (!valid) {
      setError(Object.values(validation)[0] || 'Перевірте аудиторію розсилки')
      return
    }
    if (mode !== 'draft' && !(reach > 0)) {
      setError('Дочекайтеся перевірки аудиторії або змініть сегмент')
      return
    }
    const moment = new Date(when)
    if (
      mode === 'schedule' &&
      (!Number.isFinite(moment.getTime()) || moment.getTime() <= Date.now())
    ) {
      setError('Виберіть час запуску в майбутньому')
      return
    }
    saving.current = true
    setBusy(mode)
    setError('')
    const payload = {
      ...form,
      title: form.title.trim(),
      photo_url: form.photo_url.trim() || null,
      button_text: form.button_text.trim() || null,
      button_url: form.button_url.trim() || null,
      segment: payloadSegment,
    }
    try {
      let current
      if (!savedId.current) {
        current = await api.broadcasts.create({
          ...payload,
          client_key: clientKey.current,
        })
        savedId.current = current.id
      } else current = await api.broadcasts.get(savedId.current)
      if (current.status !== 'draft') {
        notify(
          'Розсилка вже запущена або запланована. Її стан оновлено у списку.',
        )
        onSaved()
        onClose()
        return
      }
      // The ID survives a failed launch; a retry edits the same draft.
      await api.broadcasts.update(savedId.current, payload)
      if (mode === 'send') {
        await api.broadcasts.send(savedId.current)
        notify('Розсилку передано на відправлення')
      } else if (mode === 'schedule') {
        const result = await api.broadcasts.schedule(
          savedId.current,
          moment.toISOString(),
        )
        notify(
          `Заплановано: ${dateTime(result.scheduled_at || moment.toISOString())}`,
        )
      } else notify('Чернетку збережено')
      onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
      if (savedId.current) onSaved()
    } finally {
      saving.current = false
      setBusy('')
    }
  }

  return (
    <Modal
      title={source?.id ? 'Редагувати розсилку' : 'Нова розсилка'}
      className="broadcast-editor-modal"
      onClose={close}
      footer={
        <>
          <button
            type="button"
            className="btn ghost"
            disabled={disabled}
            onClick={close}
          >
            Скасувати
          </button>
          <button
            type="button"
            className="btn ghost"
            disabled={disabled || !valid}
            onClick={() => save('draft')}
          >
            {busy === 'draft' ? 'Зберігаємо…' : 'Зберегти чернетку'}
          </button>
          <button
            type="button"
            className="btn ghost"
            disabled={disabled || !valid || !(reach > 0) || !when}
            onClick={() => save('schedule')}
          >
            {busy === 'schedule' ? 'Плануємо…' : 'Запланувати'}
          </button>
          <button
            type="button"
            className="btn"
            disabled={disabled || !valid || !(reach > 0)}
            onClick={() => save('send')}
          >
            {busy === 'send' ? 'Запускаємо…' : 'Надіслати зараз'}
          </button>
        </>
      }
    >
      <form
        className="broadcast-editor-body"
        onSubmit={(e) => {
          e.preventDefault()
          save('draft')
        }}
      >
        <ErrorBar error={error} />
        <fieldset disabled={!!busy} className="broadcast-editor-grid">
          <div className="broadcast-form-main">
            <section className="broadcast-section">
              <div className="broadcast-section-title">
                <span>01</span>
                <div>
                  <h3>Повідомлення</h3>
                  <p>Текст або текст із зображенням</p>
                </div>
              </div>
              <Field
                label="Назва розсилки"
                hint="Тільки для панелі — клієнт її не бачить"
              >
                <input
                  className="input"
                  aria-label="Назва розсилки"
                  maxLength={255}
                  value={form.title}
                  onChange={set('title')}
                  placeholder="Наприклад, новинки листопада"
                />
              </Field>
              <div
                className="broadcast-format"
                role="group"
                aria-label="Формат повідомлення"
              >
                <label
                  className={form.text_format === 'plain' ? 'selected' : ''}
                >
                  <input
                    type="radio"
                    name="text-format"
                    value="plain"
                    checked={form.text_format === 'plain'}
                    onChange={set('text_format')}
                  />
                  Текст
                </label>
                <label
                  className={form.text_format === 'html' ? 'selected' : ''}
                >
                  <input
                    type="radio"
                    name="text-format"
                    value="html"
                    checked={form.text_format === 'html'}
                    onChange={set('text_format')}
                  />
                  HTML
                </label>
              </div>
              <Field
                label="Текст повідомлення"
                hint={
                  form.text_format === 'plain'
                    ? 'Пишіть звичайний текст. Символи <, > та & надсилаються без змін.'
                    : 'HTML Telegram: <b>жирний</b>, <i>курсив</i>, <u>підкреслення</u>, <a href="https://…">посилання</a>. Новий рядок — Enter.'
                }
              >
                <textarea
                  className="input broadcast-textarea"
                  aria-label="Текст повідомлення"
                  value={form.text}
                  onChange={set('text')}
                  placeholder="Напишіть повідомлення для клієнтів…"
                />
              </Field>
              <div
                className={`broadcast-length ${length > limit ? 'invalid' : ''}`}
                aria-live="polite"
              >
                <span>
                  {form.photo_url ? 'Текст із фото' : 'Текст без фото'}
                </span>
                <strong>
                  {length} / {limit}
                </strong>
              </div>
              {validation.text && form.text && (
                <p className="broadcast-validation" role="alert">
                  {validation.text}
                </p>
              )}
            </section>
            <section className="broadcast-section">
              <div className="broadcast-section-title">
                <span>02</span>
                <div>
                  <h3>Зображення</h3>
                  <p>
                    Необов’язково. Фото і текст прийдуть одним повідомленням.
                  </p>
                </div>
              </div>
              <ImageField
                label="Зображення розсилки"
                value={form.photo_url}
                onChange={(url) => setForm((f) => ({ ...f, photo_url: url }))}
                onBusyChange={setImageBusy}
                disabled={!!busy}
                hint="JPG, PNG, WebP або GIF, до 8 МБ. Надсилається як фото; для GIF використовується перший кадр."
              />
              {validation.photo_url && (
                <p className="broadcast-validation" role="alert">
                  {validation.photo_url}
                </p>
              )}
            </section>
            <section className="broadcast-section">
              <div className="broadcast-section-title">
                <span>03</span>
                <div>
                  <h3>Кнопка під повідомленням</h3>
                  <p>Залиште обидва поля порожніми, якщо кнопка не потрібна</p>
                </div>
              </div>
              <div className="grid k2">
                <Field label="Текст кнопки">
                  <input
                    className="input"
                    aria-label="Текст кнопки"
                    maxLength={64}
                    value={form.button_text}
                    onChange={set('button_text')}
                    placeholder="Відкрити магазин"
                  />
                </Field>
                <Field label="Посилання кнопки">
                  <input
                    className="input"
                    aria-label="Посилання кнопки"
                    value={form.button_url}
                    onChange={set('button_url')}
                    placeholder="https://t.me/…"
                  />
                </Field>
              </div>
              {validation.button && (
                <p className="broadcast-validation" role="alert">
                  {validation.button}
                </p>
              )}
            </section>
            <section className="broadcast-section">
              <div className="broadcast-section-title">
                <span>04</span>
                <div>
                  <h3>Аудиторія й час запуску</h3>
                  <p>Оберіть отримувачів і спосіб відправлення</p>
                </div>
              </div>
              <Field label="Кому надсилати">
                <select
                  className="input"
                  aria-label="Кому надсилати"
                  value={segment.type}
                  onChange={(e) =>
                    setSegment((s) => ({ ...s, type: e.target.value }))
                  }
                >
                  {segments.map((s) => (
                    <option key={s.type} value={s.type}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </Field>
              {segment.type === 'inactive' && (
                <Field label="Не заходили більше, днів">
                  <input
                    className="input"
                    aria-label="Не заходили більше, днів"
                    type="number"
                    min="1"
                    max="36500"
                    step="1"
                    value={segment.days}
                    onChange={(e) =>
                      setSegment((s) => ({ ...s, days: e.target.value }))
                    }
                  />
                </Field>
              )}
              {segment.type === 'top_spenders' && (
                <Field label="Витратили більше, ₴">
                  <input
                    className="input"
                    aria-label="Витратили більше, ₴"
                    type="number"
                    min="0"
                    step="0.01"
                    value={segment.min_total}
                    onChange={(e) =>
                      setSegment((s) => ({ ...s, min_total: e.target.value }))
                    }
                  />
                </Field>
              )}
              <div className="broadcast-reach" aria-live="polite">
                {reachError ? (
                  <>
                    <ErrorBar error={reachError} />
                    <button
                      type="button"
                      className="btn ghost small"
                      onClick={() => setReachRevision((v) => v + 1)}
                    >
                      Перерахувати аудиторію
                    </button>
                  </>
                ) : reach === null ? (
                  'Рахуємо отримувачів…'
                ) : reach === 0 ? (
                  'У цій аудиторії немає отримувачів. Можна зберегти чернетку.'
                ) : (
                  <>
                    Отримають повідомлення: <strong>{reach} клієнтів</strong>
                  </>
                )}
              </div>
              <Field
                label="Час запуску"
                hint={`Для кнопки «Запланувати». Час пристрою: ${Intl.DateTimeFormat().resolvedOptions().timeZone}. Черга перевіряється щогодини; тихі години враховуються.`}
              >
                <input
                  className="input"
                  aria-label="Час запуску"
                  type="datetime-local"
                  step="3600"
                  value={when}
                  onChange={(e) => setWhen(e.target.value)}
                />
              </Field>
            </section>
          </div>
          <aside className="broadcast-preview">
            <span className="broadcast-preview-label">ПОПЕРЕДНІЙ ПЕРЕГЛЯД</span>
            <div className="broadcast-message">
              {form.photo_url && (
                <img src={form.photo_url} alt="Фото в повідомленні" />
              )}
              <div className="broadcast-message-text">
                {form.text ? (
                  <BroadcastPreviewText
                    text={form.text}
                    format={form.text_format}
                  />
                ) : (
                  <span className="muted">Тут з’явиться ваше повідомлення</span>
                )}
              </div>
              {form.button_text && (
                <span className="broadcast-message-button">
                  {form.button_text}
                </span>
              )}
            </div>
            <p>
              {form.photo_url
                ? 'Одне фото з підписом'
                : 'Одне текстове повідомлення'}{' '}
              ·{' '}
              {form.text_format === 'html'
                ? 'HTML-форматування'
                : 'Звичайний текст'}
            </p>
            {imageBusy && (
              <p role="status">
                Завантаження фото… Зачекайте перед збереженням.
              </p>
            )}
          </aside>
        </fieldset>
      </form>
    </Modal>
  )
}

const DELIVERY_LABELS = {
  sending: 'Очікує результату',
  sent: 'Доставлено',
  failed: 'Не доставлено',
  retry: 'Очікує повтору',
  unknown: 'Результат невідомий',
}

function DeliveryJournal({ broadcast, onClose }) {
  const [after, setAfter] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [data, setData] = useState(null)
  const contentRef = useRef(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setData(null)
    setError('')
    api.broadcasts
      .deliveries(broadcast.id, after)
      .then((result) => {
        if (active) setData(result)
      })
      .catch((err) => {
        if (active) setError(err.message)
      })
    return () => {
      active = false
    }
  }, [broadcast.id, after, refresh])
  useEffect(() => {
    // Page changes can remove/disable the focused control. Keep keyboard focus
    // inside the dialog so Escape and its focus trap remain available.
    if (data || error)
      contentRef.current
        ?.closest('[role="dialog"]')
        ?.focus({ preventScroll: true })
  }, [data, error])
  return (
    <Modal
      title={`Журнал: ${broadcast.title}`}
      onClose={onClose}
      footer={
        <>
          <button
            className="btn ghost small"
            onClick={() => setRefresh((n) => n + 1)}
          >
            Оновити
          </button>
          <button
            className="btn ghost small"
            disabled={after === 0}
            onClick={() => setAfter(0)}
          >
            На початок
          </button>
          <button
            className="btn small"
            disabled={data?.next_cursor == null}
            onClick={() => setAfter(data.next_cursor)}
          >
            Далі
          </button>
        </>
      }
    >
      <p ref={contentRef} className="muted">
        Невідомий результат означає, що доставку неможливо підтвердити. Такі
        повідомлення автоматично не повторюються, щоб уникнути дублювання.
      </p>
      <ErrorBar error={error} />
      {!data && !error ? (
        <Loading />
      ) : (
        data && (
          <div
            className="table-wrap"
            style={{ maxHeight: 'min(45dvh, 400px)', overflow: 'auto' }}
          >
            <table>
              <thead>
                <tr>
                  <th>Клієнт</th>
                  <th>Результат</th>
                  <th>Спроб</th>
                  <th>Оновлено</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.user_id}>
                    <td>#{item.user_id}</td>
                    <td>
                      <span>{DELIVERY_LABELS[item.status] || item.status}</span>
                      {item.error && <div className="faint">{item.error}</div>}
                      {item.next_attempt_at && (
                        <div className="faint">
                          Повтор: {dateTime(item.next_attempt_at)}
                        </div>
                      )}
                    </td>
                    <td>{item.attempts}</td>
                    <td>{dateTime(item.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.items.length && (
              <p className="muted">Записів доставок ще немає.</p>
            )}
          </div>
        )
      )}
    </Modal>
  )
}

export default function Broadcasts() {
  const notify = useToast()
  const [items, setItems] = useState(null)
  const [segments, setSegments] = useState([])
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [journal, setJournal] = useState(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [pending, setPending] = useState(null)
  const actionLock = useRef(false)
  const load = useCallback(async () => {
    try {
      const [list, segs] = await Promise.all([
        api.broadcasts.list(),
        api.broadcasts.segments(),
      ])
      setItems(list)
      setSegments(segs)
      setError('')
    } catch (err) {
      setError(err.message)
    }
  }, [])
  useEffect(() => {
    load()
  }, [load])
  const active = Boolean(
    items?.some((b) => ['sending', 'scheduled'].includes(b.status)),
  )
  useVisiblePolling(load, 4000, { enabled: active })
  const action = async (broadcast, kind) => {
    if (actionLock.current) return
    if (
      kind === 'send' &&
      !confirm(
        `${broadcast.status === 'failed' ? 'Продовжити' : 'Надіслати'} «${broadcast.title}»? Збережені результати не надсилатимуться повторно.`,
      )
    )
      return
    if (kind === 'remove' && !confirm(`Видалити «${broadcast.title}»?`)) return
    actionLock.current = true
    setPending(broadcast.id)
    try {
      await api.broadcasts[kind](broadcast.id)
      notify(
        kind === 'send'
          ? 'Розсилка стартувала'
          : kind === 'remove'
            ? 'Розсилку видалено'
            : 'Розсилку знято з черги',
      )
      await load()
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      actionLock.current = false
      setPending(null)
    }
  }
  const segmentLabel = (segment) => {
    const found = segments.find((s) => s.type === segment?.type)
    return `${found?.label || 'Усі клієнти'}${segment?.days ? ` · ${segment.days} дн` : ''}${segment?.min_total ? ` · від ${segment.min_total} ₴` : ''}`
  }
  const filtered = (items || []).filter(
    (b) =>
      (filter === 'all' || b.status === filter) &&
      `${b.title} ${plainBroadcastText(b.text, b.text_format || 'html')}`
        .toLocaleLowerCase('uk')
        .includes(query.trim().toLocaleLowerCase('uk')),
  )
  const currentPage = Math.min(
    page,
    Math.max(1, Math.ceil(filtered.length / 20)),
  )
  const visible = filtered.slice((currentPage - 1) * 20, currentPage * 20)
  const counts = (items || []).reduce(
    (sum, b) => {
      sum[b.status] = (sum[b.status] || 0) + 1
      sum.delivered += b.sent_count || 0
      return sum
    },
    { delivered: 0 },
  )
  return (
    <div className="broadcasts-page">
      <div className="page-head">
        <div>
          <h1>Розсилки</h1>
          <p>Повідомлення клієнтам: текст, фото, аудиторії та планування</p>
        </div>
        <button
          className="btn"
          disabled={!segments.length}
          onClick={() => setEditing({})}
        >
          Створити розсилку
        </button>
      </div>
      <ErrorBar error={error} />
      {error && (
        <button className="btn ghost small" onClick={load}>
          Оновити список
        </button>
      )}
      {items && (
        <div className="broadcast-stats">
          <div>
            <span>Розсилок</span>
            <strong>{items.length}</strong>
          </div>
          <div>
            <span>Чернетки</span>
            <strong>{counts.draft || 0}</strong>
          </div>
          <div>
            <span>У черзі та в роботі</span>
            <strong>{(counts.scheduled || 0) + (counts.sending || 0)}</strong>
          </div>
          <div>
            <span>Доставлено повідомлень</span>
            <strong>{counts.delivered}</strong>
          </div>
        </div>
      )}
      <div className="broadcast-toolbar">
        <input
          className="input"
          type="search"
          aria-label="Пошук розсилок"
          placeholder="Знайти за назвою або текстом…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setPage(1)
          }}
        />
        <select
          className="input"
          aria-label="Статус розсилок"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value)
            setPage(1)
          }}
        >
          <option value="all">Усі статуси</option>
          {Object.entries(STATUS_CHIP).map(([value, s]) => (
            <option key={value} value={value}>
              {s.label}
            </option>
          ))}
        </select>
        <button className="btn ghost" onClick={load}>
          Оновити
        </button>
      </div>
      {!items ? (
        !error && <Loading />
      ) : !items.length ? (
        <Empty title="Розсилок немає">
          Створіть перше повідомлення або збережіть чернетку.
        </Empty>
      ) : !visible.length ? (
        <Empty title="Нічого не знайдено">
          <button
            className="btn ghost small"
            onClick={() => {
              setQuery('')
              setFilter('all')
            }}
          >
            Скинути фільтри
          </button>
        </Empty>
      ) : (
        <>
          <div className="broadcast-list">
            {visible.map((b) => {
              const chip = STATUS_CHIP[b.status] || STATUS_CHIP.draft
              return (
                <article
                  className="broadcast-card"
                  key={b.id}
                  aria-label={b.title}
                >
                  <div className="broadcast-card-content">
                    {b.photo_url ? (
                      <img
                        className="broadcast-card-image"
                        src={b.photo_url}
                        alt=""
                        loading="lazy"
                      />
                    ) : (
                      <span className="broadcast-text-icon" aria-hidden="true">
                        Aa
                      </span>
                    )}
                    <div className="broadcast-card-description">
                      <div className="broadcast-card-title">
                        <h3>{b.title}</h3>
                        <span className={`chip ${chip.cls}`}>{chip.label}</span>
                      </div>
                      <p>
                        {plainBroadcastText(
                          b.text,
                          b.text_format || 'html',
                        ).slice(0, 160)}
                      </p>
                      <span className="muted">
                        {segmentLabel(b.segment)} ·{' '}
                        {b.photo_url ? 'Текст і фото' : 'Текст'} ·{' '}
                        {dateTime(b.created_at)}
                      </span>
                    </div>
                  </div>
                  <div className="broadcast-delivery-summary">
                    <span>
                      <strong>{b.sent_count || 0}</strong> доставлено
                    </span>
                    {b.failed_count > 0 && (
                      <span className="broadcast-validation">
                        {b.failed_count} не доставлено
                      </span>
                    )}
                    {b.unknown_count > 0 && (
                      <span>{b.unknown_count} невідомих результатів</span>
                    )}
                  </div>
                  {b.status === 'sending' && (
                    <div className="muted">
                      {b.lease_until && new Date(b.lease_until) > new Date()
                        ? b.heartbeat_at
                          ? 'Виконується / очікує повтору'
                          : 'Очікує запуску'
                        : 'Очікує автоматичного відновлення'}
                    </div>
                  )}
                  {b.status === 'scheduled' && b.scheduled_at && (
                    <div className="muted">
                      Запуск: {dateTime(b.scheduled_at)}
                    </div>
                  )}
                  {b.last_error && (
                    <div className="broadcast-last-error">{b.last_error}</div>
                  )}
                  <div className="broadcast-card-actions">
                    <button
                      className="btn ghost small"
                      onClick={() => setJournal(b)}
                    >
                      Журнал
                    </button>
                    {b.status === 'draft' && (
                      <button
                        className="btn ghost small"
                        disabled={pending !== null}
                        onClick={() => setEditing(b)}
                      >
                        Редагувати
                      </button>
                    )}
                    <button
                      className="btn ghost small"
                      disabled={pending !== null}
                      onClick={() =>
                        setEditing({
                          ...b,
                          id: undefined,
                          title: `${b.title.slice(0, 240)} — копія`,
                        })
                      }
                    >
                      Дублювати
                    </button>
                    {['draft', 'scheduled', 'failed'].includes(b.status) && (
                      <button
                        className="btn small"
                        disabled={pending !== null}
                        onClick={() => action(b, 'send')}
                      >
                        {pending === b.id
                          ? 'Зачекайте…'
                          : b.status === 'failed'
                            ? 'Продовжити'
                            : 'Надіслати зараз'}
                      </button>
                    )}
                    {b.status === 'scheduled' && (
                      <button
                        className="btn ghost small"
                        disabled={pending !== null}
                        onClick={() => action(b, 'unschedule')}
                      >
                        Зняти з черги
                      </button>
                    )}
                    {b.status !== 'sending' && (
                      <button
                        className="btn danger small"
                        disabled={pending !== null}
                        onClick={() => action(b, 'remove')}
                      >
                        Видалити
                      </button>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
          <Pagination
            page={currentPage}
            total={filtered.length}
            size={20}
            count={visible.length}
            onPage={setPage}
          />
        </>
      )}
      {journal && (
        <DeliveryJournal broadcast={journal} onClose={() => setJournal(null)} />
      )}
      {editing && (
        <BroadcastForm
          source={editing}
          segments={segments}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </div>
  )
}
