import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { haptic } from '../telegram'

const STATUS = {
  new: 'Нове',
  confirmed: 'Підтверджено',
  accepted: 'Прийнято в роботу',
  paid: 'Оплачено',
  shipped: 'Відправлено',
  done: 'Виконано',
  cancelled: 'Скасовано',
}

const OPEN = ['new', 'confirmed', 'accepted', 'paid', 'shipped']

function clock(value) {
  if (!value) return ''
  return new Date(value).toLocaleString('uk-UA', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

/** Список замовлень, у межах яких можна писати оператору. */
export function ChatList({ config, orders, onOpen }) {
  const open = (orders || []).filter((o) => OPEN.includes(o.status))

  if (open.length === 0) {
    return (
      <div className="empty">
        <h2>Немає активних замовлень</h2>
        <p>Чат з оператором відкривається після оформлення замовлення.</p>
      </div>
    )
  }

  return (
    <>
      <div className="head">
        <h1>Чат з оператором</h1>
        <p>Оберіть замовлення — кожне веде окрему розмову</p>
      </div>

      {open.map((o) => (
        <button key={o.id} className="order chat-pick" onClick={() => onOpen(o)}>
          <div className="order-head">
            <span>№{o.id}</span>
            <span className="num">
              {Number(o.total).toFixed(0)} {config.currency}
            </span>
          </div>
          <div className="hint">
            {clock(o.created_at)} · {STATUS[o.status] || o.status}
          </div>
        </button>
      ))}
    </>
  )
}

export function ChatRoom({ config, order, onBack }) {
  const [messages, setMessages] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const bottom = useRef(null)

  const load = useCallback(
    (silent = false) => {
      api.chat
        .list(order.id)
        .then(setMessages)
        .catch((err) => !silent && setError(err.message))
    },
    [order.id],
  )

  useEffect(() => load(), [load])

  // Оператор відповідає з панелі, тож стрічку доводиться підтягувати самим
  useEffect(() => {
    // Згорнутий Mini App не показує стрічку — не витрачаємо на нього запити
    const poll = () => !document.hidden && load(true)
    const timer = setInterval(poll, 12000)
    document.addEventListener('visibilitychange', poll)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', poll)
    }
  }, [load])

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const send = async () => {
    const body = text.trim()
    if (!body) return
    setBusy(true)
    setError('')
    try {
      const sent = await api.chat.send(order.id, body)
      setMessages((prev) => [...(prev || []), sent])
      setText('')
      haptic('light')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="chat-screen">
      <div className="head">
        <button className="chip" onClick={onBack} style={{ marginBottom: 8 }}>
          ← Замовлення
        </button>
        <h1 style={{ fontSize: 18 }}>Замовлення №{order.id}</h1>
        <p>{STATUS[order.status] || order.status}</p>
      </div>

      {error && <div className="banner warn">{error}</div>}

      <div className="chat-log">
        {messages === null ? (
          <div className="skeleton" style={{ height: 48 }} />
        ) : messages.length === 0 ? (
          <p className="hint" style={{ padding: '0 14px' }}>
            Напишіть питання — оператор відповість сюди й у чат із ботом.
          </p>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`bubble ${m.direction === 'in' ? 'mine' : ''}`}>
              <div className="bubble-head">
                {m.direction === 'in' ? 'Ви' : m.author || 'Оператор'} · {clock(m.created_at)}
              </div>
              {m.text && <div className="bubble-text">{m.text}</div>}
              {m.file_kind && (
                <div className="bubble-head">
                  Вкладення: {m.file_name || m.file_kind}
                </div>
              )}
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>

      <div className="chat-compose">
        <input
          className="input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="Повідомлення оператору"
        />
        <button className="add" onClick={send} disabled={busy || !text.trim()}>
          {busy ? '…' : 'Надіслати'}
        </button>
      </div>
    </div>
  )
}
