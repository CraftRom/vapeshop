import { useCallback, useEffect, useState } from 'react'

import { api } from '../api'
import { Empty, ErrorBar, Field, Loading, Modal, dateTime, useToast } from '../components/ui'

const STATUS_CHIP = {
  draft: { label: 'Чернетка', cls: '' },
  scheduled: { label: 'Заплановано', cls: 'warn' },
  sending: { label: 'Надсилається', cls: 'warn' },
  sent: { label: 'Надіслано', cls: 'ok' },
  failed: { label: 'Помилка', cls: 'bad' },
}

/** Найближча ціла година в майбутньому, у форматі для datetime-local.
 *
 * Планувальник має годинну точність, тож пропонувати хвилини було б
 * обіцянкою, якої система не виконує.
 */
function nextHourLocal() {
  const d = new Date()
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`
}

const NEEDS_DAYS = ['inactive']
const NEEDS_TOTAL = ['top_spenders']

function BroadcastForm({ segments, onClose, onSaved }) {
  const notify = useToast()
  const [form, setForm] = useState({
    title: '',
    text: '',
    photo_url: '',
    button_text: '',
    button_url: '',
  })
  const [segment, setSegment] = useState({ type: 'all', days: 30, min_total: 1000 })
  const [reach, setReach] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [when, setWhen] = useState(nextHourLocal)

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const payloadSegment = useCallback(() => {
    const base = { type: segment.type }
    if (NEEDS_DAYS.includes(segment.type)) base.days = Number(segment.days)
    if (NEEDS_TOTAL.includes(segment.type)) base.min_total = Number(segment.min_total)
    return base
  }, [segment])

  useEffect(() => {
    let cancelled = false
    setReach(null)
    api.broadcasts
      .preview(payloadSegment())
      .then((data) => !cancelled && setReach(data.count))
      .catch(() => !cancelled && setReach(null))
    return () => { cancelled = true }
  }, [payloadSegment])

  const save = async (mode) => {
    setBusy(true)
    setError('')
    try {
      const created = await api.broadcasts.create({
        title: form.title,
        text: form.text,
        photo_url: form.photo_url || null,
        button_text: form.button_text || null,
        button_url: form.button_url || null,
        segment: payloadSegment(),
      })
      if (mode === 'send') {
        await api.broadcasts.send(created.id)
        notify(`Розсилка стартувала — ${reach ?? 0} отримувачів`)
      } else if (mode === 'schedule') {
        // Час із поля — локальний; toISOString переводить його в UTC,
        // у якому живе планувальник.
        await api.broadcasts.schedule(created.id, new Date(when).toISOString())
        notify(`Заплановано на ${new Date(when).toLocaleString('uk-UA')}`)
      } else {
        notify('Чернетку збережено')
      }
      onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const valid = form.title.trim() && form.text.trim()

  return (
    <Modal
      title="Нова розсилка"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Скасувати</button>
          <button className="btn ghost" onClick={() => save('draft')} disabled={busy || !valid}>
            Зберегти чернетку
          </button>
          <button
            className="btn ghost"
            onClick={() => save('schedule')}
            disabled={busy || !valid || !reach || !when}
          >
            Запланувати
          </button>
          <button className="btn" onClick={() => save('send')} disabled={busy || !valid || !reach}>
            Надіслати зараз
          </button>
        </>
      }
    >
      <div className="stack">
        <ErrorBar error={error} />

        <Field label="Назва" hint="Тільки для панелі — клієнт її не бачить">
          <input className="input" value={form.title} onChange={set('title')} autoFocus />
        </Field>

        <Field label="Текст повідомлення" hint="Підтримується HTML: <b>жирний</b>, <i>курсив</i>">
          <textarea className="input" value={form.text} onChange={set('text')} />
        </Field>

        <Field label="Посилання на зображення">
          <input className="input" value={form.photo_url} onChange={set('photo_url')} />
        </Field>

        <div className="grid k2">
          <Field label="Текст кнопки">
            <input className="input" value={form.button_text} onChange={set('button_text')} />
          </Field>
          <Field label="Посилання кнопки">
            <input className="input" value={form.button_url} onChange={set('button_url')} />
          </Field>
        </div>

        <Field
          label="Час запуску"
          hint={
            'Для кнопки «Запланувати». Планувальник перевіряє чергу раз на годину, ' +
            'тож хвилини округляються вниз. У тихі години розсилка не піде — ' +
            'дочекається ранку й стартує тоді.'
          }
        >
          <input
            className="input"
            type="datetime-local"
            step="3600"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
          />
        </Field>

        <Field label="Кому надсилати">
          <select
            className="input"
            value={segment.type}
            onChange={(e) => setSegment((s) => ({ ...s, type: e.target.value }))}
          >
            {segments.map((s) => (
              <option key={s.type} value={s.type}>{s.label}</option>
            ))}
          </select>
        </Field>

        {NEEDS_DAYS.includes(segment.type) && (
          <Field label="Не заходили більше, днів">
            <input
              className="input"
              type="number"
              min="1"
              value={segment.days}
              onChange={(e) => setSegment((s) => ({ ...s, days: e.target.value }))}
            />
          </Field>
        )}

        {NEEDS_TOTAL.includes(segment.type) && (
          <Field label="Витратили більше, ₴">
            <input
              className="input"
              type="number"
              min="0"
              value={segment.min_total}
              onChange={(e) => setSegment((s) => ({ ...s, min_total: e.target.value }))}
            />
          </Field>
        )}

        <div className="card" style={{ background: 'var(--panel-2)' }}>
          {reach === null ? (
            <span className="muted">Рахуємо охоплення…</span>
          ) : reach === 0 ? (
            <span className="muted">У цьому сегменті зараз нікого немає — оберіть інший.</span>
          ) : (
            <span>
              Отримають повідомлення: <strong className="mono">{reach}</strong> клієнтів
            </span>
          )}
        </div>
      </div>
    </Modal>
  )
}

export default function Broadcasts() {
  const notify = useToast()
  const [items, setItems] = useState(null)
  const [segments, setSegments] = useState([])
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setError('')
    try {
      const [list, segs] = await Promise.all([api.broadcasts.list(), api.broadcasts.segments()])
      setItems(list)
      setSegments(segs)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Поки щось надсилається — оновлюємо лічильники
  useEffect(() => {
    if (!items?.some((b) => b.status === 'sending')) return
    const timer = setInterval(load, 4000)
    return () => clearInterval(timer)
  }, [items, load])

  const unschedule = async (broadcast) => {
    try {
      await api.broadcasts.unschedule(broadcast.id)
      notify('Розсилку знято з черги — повернулась у чернетки')
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const send = async (broadcast) => {
    if (!confirm(`Надіслати «${broadcast.title}»? Скасувати вже не вийде.`)) return
    try {
      await api.broadcasts.send(broadcast.id)
      notify('Розсилка стартувала')
      load()
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  const remove = async (broadcast) => {
    if (!confirm(`Видалити «${broadcast.title}»?`)) return
    try {
      await api.broadcasts.remove(broadcast.id)
      notify('Розсилку видалено')
      load()
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  const segmentLabel = (segment) => {
    const found = segments.find((s) => s.type === segment?.type)
    let label = found?.label || 'Усі клієнти'
    if (segment?.days) label += ` (${segment.days} дн)`
    if (segment?.min_total) label += ` (від ${segment.min_total} ₴)`
    return label
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Розсилки</h1>
          <p>Повідомлення клієнтам у боті — з вибором сегмента отримувачів</p>
        </div>
        <button className="btn" onClick={() => setCreating(true)} disabled={!segments.length}>
          Створити розсилку
        </button>
      </div>

      <ErrorBar error={error} />

      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty title="Розсилок немає">
          Створіть першу — наприклад, повідомлення про нове надходження для тих, хто вже купував.
        </Empty>
      ) : (
        <div className="card" style={{ padding: '18px 6px' }}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Розсилка</th>
                  <th>Сегмент</th>
                  <th className="num">Доставлено</th>
                  <th>Статус</th>
                  <th>Створено</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((b) => {
                  const chip = STATUS_CHIP[b.status] || STATUS_CHIP.draft
                  return (
                    <tr key={b.id}>
                      <td>
                        {b.title}
                        <div className="faint">{b.text.slice(0, 70)}{b.text.length > 70 ? '…' : ''}</div>
                      </td>
                      <td className="muted">{segmentLabel(b.segment)}</td>
                      <td className="num">
                        {b.sent_count}
                        {b.failed_count > 0 && (
                          <span className="faint"> · {b.failed_count} не дійшло</span>
                        )}
                      </td>
                      <td>
                        <span className={`chip ${chip.cls}`}>{chip.label}</span>
                        {b.status === 'scheduled' && b.scheduled_at && (
                          <div className="faint">{dateTime(b.scheduled_at)}</div>
                        )}
                      </td>
                      <td className="faint">{dateTime(b.created_at)}</td>
                      <td>
                        <div className="row">
                          {(b.status === 'draft' || b.status === 'scheduled') && (
                            <button className="btn small" onClick={() => send(b)}>
                              Надіслати зараз
                            </button>
                          )}
                          {b.status === 'scheduled' && (
                            <button className="btn ghost small" onClick={() => unschedule(b)}>
                              Зняти з черги
                            </button>
                          )}
                          {b.status !== 'sending' && (
                            <button className="btn danger small" onClick={() => remove(b)}>Видалити</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {creating && (
        <BroadcastForm
          segments={segments}
          onClose={() => setCreating(false)}
          onSaved={load}
        />
      )}
    </>
  )
}
