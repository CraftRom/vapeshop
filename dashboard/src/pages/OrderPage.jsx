import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api, getToken } from '../api'
import { ErrorBar, Field, Loading, Modal, money, useToast } from '../components/ui'
import { allowedFrom, stagesFor } from '../components/StatusRail'

// Спосіб доставки, обраний покупцем. Порожнє значення — замовлення з
// часів, коли вибору не було: тоді все писалося одним рядком адреси.
const DELIVERY_METHODS = {
  warehouse: 'Відділення НП',
  courier: 'Курʼєр',
}

const PAYMENT = { card: 'На картку', cod: 'Накладений платіж' }

// Повні підписи кроків. Доріжка й дозволені переходи живуть у StatusRail —
// дві копії тих самих таблиць уже розходились між списком і карткою.
const STAGE_LABELS = {
  new: 'Нове',
  accepted: 'Прийнято',
  paid: 'Оплачено',
  shipped: 'Відправлено',
  done: 'Виконано',
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

/** Вікно введення накладної.
 *
 * Раніше менеджер мусив спершу вписати номер у поле нижче, а тоді натиснути
 * «Відправлено» — і без цього отримував відмову. Порядок неочевидний, тож
 * запитуємо номер саме тоді, коли він потрібен.
 */
function TrackingModal({ initial, onCancel, onConfirm }) {
  const [value, setValue] = useState(initial || '')
  const [busy, setBusy] = useState(false)

  const confirm = async () => {
    setBusy(true)
    await onConfirm(value.trim())
    setBusy(false)
  }

  return (
    <Modal
      title="Відправлення замовлення"
      onClose={onCancel}
      footer={
        <>
          <button className="btn ghost" onClick={onCancel}>Скасувати</button>
          <button className="btn" onClick={confirm} disabled={busy || !value.trim()}>
            {busy ? 'Надсилаємо…' : 'Відправити й надіслати ТТН'}
          </button>
        </>
      }
    >
      <Field
        label="Номер накладної"
        hint="Клієнт отримає його в Telegram одразу після підтвердження"
      >
        <input
          className="input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="20450912345678"
          autoFocus
          onKeyDown={(e) => e.key === 'Enter' && value.trim() && confirm()}
        />
      </Field>
    </Modal>
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
                {m.direction === 'out' ? m.author || 'Менеджер' : m.author || 'Клієнт'}
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
  const [params, setParams] = useSearchParams()
  const notify = useToast()

  const [order, setOrder] = useState(null)
  const [messages, setMessages] = useState([])
  const [error, setError] = useState('')
  const [tracking, setTracking] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [askTracking, setAskTracking] = useState(false)

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

  // Прийшли зі списку по кнопці «Відпр.» — одразу питаємо накладну
  useEffect(() => {
    if (order && params.get('ship') === '1' && order.status !== 'shipped') {
      setAskTracking(true)
      setParams({}, { replace: true })
    }
  }, [order, params, setParams])

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
    // Накладну питаємо у вікні: це єдиний статус, який без неї не має сенсу
    if (status === 'shipped') {
      setAskTracking(true)
      return
    }
    await patch({ status }, 'Статус змінено')
  }

  const confirmShipping = async (value) => {
    setTracking(value)
    await patch(
      { status: 'shipped', tracking_number: value },
      'Відправлено, ТТН надіслано клієнту',
    )
    setAskTracking(false)
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
              {stagesFor(order.payment_method).map((s) => {
                const current = order.status === s.key
                const reachable = allowedFrom(order.status, order.payment_method)
                  .includes(s.key)
                return (
                  <button
                    key={s.key}
                    className={current ? 'btn small' : 'btn ghost small'}
                    disabled={busy || current || !reachable}
                    title={
                      current ? 'Поточний статус'
                        : reachable ? '' : 'Недоступно з поточного статусу'
                    }
                    onClick={() => changeStatus(s.key)}
                  >
                    {STAGE_LABELS[s.key] || s.label}
                  </button>
                )
              })}
            </div>

            {allowedFrom(order.status, order.payment_method).includes('cancelled') && (
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
              {DELIVERY_METHODS[order.delivery_method] || 'Доставка'}:{' '}
              {[order.delivery_city, order.delivery_address].filter(Boolean).join(', ')}
            </p>
            {/* Коди довідника показуємо лише тоді, коли вони є: у
                замовленнях, оформлених до появи вибору відділення, їх
                немає й не буде. Порожній рядок «Код: —» лише збивав би
                з пантелику того, хто створює накладну. */}
            {order.delivery_warehouse_ref && (
              <p className="faint" style={{ margin: '0 0 4px', fontSize: 12 }}>
                Коди НП: {order.delivery_city_ref} / {order.delivery_warehouse_ref}
              </p>
            )}
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

      {askTracking && (
        <TrackingModal
          initial={tracking}
          onCancel={() => setAskTracking(false)}
          onConfirm={confirmShipping}
        />
      )}
    </>
  )
}
