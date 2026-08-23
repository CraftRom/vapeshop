import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api, getToken } from '../api'
import { ErrorBar, Field, Loading, money, useToast } from '../components/ui'

const STATUS_FLOW = [
  { value: 'new', label: 'Нове' },
  { value: 'confirmed', label: 'Підтверджено' },
  { value: 'accepted', label: 'Прийнято' },
  { value: 'paid', label: 'Оплачено' },
  { value: 'shipped', label: 'Відправлено' },
  { value: 'done', label: 'Виконано' },
]

const PAYMENT = { card: 'На картку', cod: 'Накладений платіж' }

// Дзеркало ALLOWED_TRANSITIONS з бекенду: кнопки недоступних переходів
// гасимо, щоб оператор не тицяв навмання й не ловив 409
const ALLOWED = {
  new: ['confirmed', 'cancelled'],
  confirmed: ['accepted', 'cancelled'],
  accepted: ['paid', 'shipped', 'cancelled'],
  paid: ['shipped', 'cancelled'],
  shipped: ['done', 'cancelled'],
  done: [],
  cancelled: [],
}

function timestamp(value) {
  if (!value) return ''
  return new Date(value).toLocaleString('uk-UA', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

const FILE_LABEL = {
  photo: 'Фото', document: 'Документ', video: 'Відео', voice: 'Голосове',
}

/** Вкладення з Telegram.
 *
 * Файл віддає бекенд, і запит потребує токена — тож картинку не можна
 * просто підставити в src. Тягнемо як blob і показуємо з обʼєктного URL.
 */
function Attachment({ orderId, message }) {
  const [url, setUrl] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let revoked = null
    let cancelled = false
    fetch(api.orders.fileUrl(orderId, message.id), {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((blob) => {
        if (cancelled) return
        revoked = URL.createObjectURL(blob)
        setUrl(revoked)
      })
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [orderId, message.id])

  const label = FILE_LABEL[message.file_kind] || 'Файл'

  if (failed) {
    return (
      <div className="faint" style={{ fontSize: 12.5 }}>
        {label} недоступний — Telegram видаляє старі вкладення
      </div>
    )
  }
  if (!url) return <div className="faint" style={{ fontSize: 12.5 }}>{label} завантажується…</div>

  if (message.file_kind === 'photo') {
    return (
      <a href={url} target="_blank" rel="noreferrer">
        <img src={url} alt={label} className="bubble-photo" />
      </a>
    )
  }
  if (message.file_kind === 'voice') {
    return <audio controls src={url} style={{ width: '100%', marginTop: 6 }} />
  }
  if (message.file_kind === 'video') {
    return <video controls src={url} className="bubble-photo" />
  }
  return (
    <a href={url} download={message.file_name || 'file'} className="btn ghost small"
       style={{ marginTop: 6, display: 'inline-block' }}>
      ↓ {message.file_name || label}
    </a>
  )
}

function Chat({ orderId, messages, onSent }) {
  const notify = useToast()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const bottom = useRef(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const send = async () => {
    const body = text.trim()
    if (!body) return
    setBusy(true)
    try {
      const result = await api.orders.sendMessage(orderId, body)
      setText('')
      // Клієнт міг заблокувати бота — повідомлення збережеться, але не дійде
      if (!result.delivered) notify(result.warning || 'Не доставлено клієнту', 'bad')
      onSent()
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  const onKeyDown = (e) => {
    // Enter надсилає, Shift+Enter — новий рядок
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Листування</h2>

      <div className="chat-log">
        {messages.length === 0 ? (
          <p className="faint" style={{ margin: 0 }}>
            Повідомлень ще немає. Клієнт отримає ваше в чаті з ботом і зможе
            відповісти прямо звідти.
          </p>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`bubble ${m.direction === 'out' ? 'mine' : ''}`}>
              <div className="bubble-head faint">
                {m.direction === 'out' ? m.author || 'Оператор' : m.author || 'Клієнт'}
                {' · '}
                {timestamp(m.created_at)}
              </div>
              {m.text && <div className="bubble-text">{m.text}</div>}
              {m.file_kind && <Attachment orderId={orderId} message={m} />}
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>

      <textarea
        className="input"
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Повідомлення клієнту. Enter — надіслати, Shift+Enter — новий рядок"
      />
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 10 }}>
        <button className="btn" onClick={send} disabled={busy || !text.trim()}>
          {busy ? 'Надсилаємо…' : 'Надіслати'}
        </button>
      </div>
    </div>
  )
}

export default function OrderPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const notify = useToast()

  const [order, setOrder] = useState(null)
  const [messages, setMessages] = useState([])
  const [error, setError] = useState('')
  const [tracking, setTracking] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [fresh, log] = await Promise.all([
        api.orders.get(id),
        api.orders.messages(id, true),
      ])
      setOrder(fresh)
      setMessages(log)
      setTracking(fresh.tracking_number || '')
      setNote(fresh.admin_note || '')
    } catch (err) {
      setError(err.message)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  // Відповідь клієнта приходить у бот, а не в панель — тож підтягуємо самі
  useEffect(() => {
    // Прихована вкладка нічого не показує, а кожен запит на Vercel —
    // це виклик функції. Опитуємо лише коли на сторінку дивляться.
    const poll = () => {
      if (document.hidden) return
      api.orders.messages(id).then(setMessages).catch(() => {})
    }
    const timer = setInterval(poll, 15000)
    document.addEventListener('visibilitychange', poll)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', poll)
    }
  }, [id])

  const patch = async (payload, okText) => {
    setBusy(true)
    try {
      const fresh = await api.orders.patch(id, payload)
      setOrder(fresh)
      notify(okText)
      load()
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  const changeStatus = async (status) => {
    if (status === 'shipped' && !tracking.trim()) {
      notify('Спочатку впишіть номер накладної — клієнт отримає його автоматично', 'bad')
      return
    }
    await patch(
      status === 'shipped'
        ? { status, tracking_number: tracking.trim() }
        : { status },
      status === 'shipped' ? 'Відправлено, ТТН надіслано клієнту' : 'Статус змінено',
    )
  }

  if (error && !order) return <ErrorBar error={error} />
  if (!order) return <Loading />

  const client = order.user || {}

  return (
    <>
      <div className="page-head">
        <div>
          <button className="btn ghost small" onClick={() => navigate('/orders')}>
            ← До списку
          </button>
          <h1 style={{ marginTop: 8 }}>Замовлення №{order.id}</h1>
          <p>
            {timestamp(order.created_at)} · {PAYMENT[order.payment_method] || order.payment_method}
            {order.operator_name && ` · веде ${order.operator_name}`}
          </p>
        </div>
      </div>

      <ErrorBar error={error} />

      <div className="order-grid">
        <div>
          <div className="card" style={{ marginBottom: 18 }}>
            <h2 style={{ marginTop: 0 }}>Статус</h2>
            <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
              {STATUS_FLOW.map((s) => {
                const current = order.status === s.value
                const reachable = (ALLOWED[order.status] || []).includes(s.value)
                return (
                  <button
                    key={s.value}
                    className={current ? 'btn small' : 'btn ghost small'}
                    disabled={busy || current || !reachable}
                    title={
                      current ? 'Поточний статус'
                        : reachable ? '' : 'Недоступно з поточного статусу'
                    }
                    onClick={() => changeStatus(s.value)}
                  >
                    {s.label}
                  </button>
                )
              })}
            </div>

            {(ALLOWED[order.status] || []).includes('cancelled') && (
              <button
                className="btn danger small"
                style={{ marginTop: 10 }}
                disabled={busy}
                onClick={() => {
                  // Скасування необоротне: повертає залишки й бонуси,
                  // а зворотного шляху зі скасованого немає
                  if (confirm(`Скасувати замовлення №${order.id}? Це необоротно.`)) {
                    changeStatus('cancelled')
                  }
                }}
              >
                Скасувати замовлення
              </button>
            )}

            <Field
              label="Номер накладної"
              hint="При переході в «Відправлено» надсилається клієнту автоматично"
            >
              <div className="row">
                <input
                  className="input"
                  value={tracking}
                  onChange={(e) => setTracking(e.target.value)}
                  placeholder="20450912345678"
                />
                <button
                  className="btn ghost"
                  disabled={busy || !tracking.trim() || tracking.trim() === order.tracking_number}
                  onClick={() => patch({ tracking_number: tracking.trim() }, 'Накладну збережено')}
                >
                  Зберегти
                </button>
              </div>
            </Field>

            <Field label="Нотатка менеджера" hint="Клієнт її не бачить">
              <textarea
                className="input"
                rows={2}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>
            <button
              className="btn ghost small"
              disabled={busy || note === (order.admin_note || '')}
              onClick={() => patch({ admin_note: note }, 'Нотатку збережено')}
            >
              Зберегти нотатку
            </button>
          </div>

          <div className="card">
            <h2 style={{ marginTop: 0 }}>Замовлення</h2>
            <div className="table-wrap">
              <table>
                <tbody>
                  {order.items.map((i, idx) => (
                    <tr key={idx}>
                      <td>{i.name}</td>
                      <td className="num">× {i.qty}</td>
                      <td className="num">{money(i.price * i.qty)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row-between" style={{ marginTop: 10 }}>
              <span className="faint">Знижка / бонуси</span>
              <span className="num">{money(order.discount)} / {money(order.bonus_used)}</span>
            </div>
            <div className="row-between" style={{ fontWeight: 700, fontSize: 17 }}>
              <span>До сплати</span>
              <span className="num">{money(order.total)}</span>
            </div>
          </div>
        </div>

        <div>
          <div className="card" style={{ marginBottom: 18 }}>
            <h2 style={{ marginTop: 0 }}>Клієнт</h2>
            <p style={{ margin: '0 0 4px' }}>{order.contact_name}</p>
            <p className="faint" style={{ margin: '0 0 4px' }}>{order.contact_phone}</p>
            <p className="faint" style={{ margin: '0 0 4px' }}>
              {order.delivery_city}, {order.delivery_address}
            </p>
            {client.username && <p className="faint" style={{ margin: 0 }}>@{client.username}</p>}
            {order.comment && (
              <p style={{ marginTop: 10 }}>
                <span className="faint">Коментар: </span>
                {order.comment}
              </p>
            )}
          </div>

          <Chat orderId={id} messages={messages} onSent={load} />
        </div>
      </div>
    </>
  )
}
