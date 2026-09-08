import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { Field } from '../fields'
import { haptic, notify } from '../telegram'

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

/** Список замовлень, у межах яких можна писати менеджеру. */
export function ChatList({ config, orders, onOpen }) {
  const open = (orders || []).filter((o) => OPEN.includes(o.status))

  if (open.length === 0) {
    return (
      <div className="empty">
        <h2>Немає активних замовлень</h2>
        <p>Чат з менеджером відкривається після оформлення замовлення.</p>
      </div>
    )
  }

  return (
    <>
      <div className="head">
        <h1>Чат з менеджером</h1>
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

/** Вкладення у стрічці: спершу мініатюра, за дотиком — на весь екран.
 *
 * Раніше тут був рядок «Вкладення: screenshot.jpg» — тобто людина
 * бачила, що щось надіслала, але не бачила, що саме. Для квитанції це
 * особливо погано: помилилися файлом — дізнаєтесь від менеджера.
 *
 * Тягнемо двійкові дані, а не ставимо посилання в src: до запиту треба
 * додати підпис Telegram, а тег <img> заголовків не надсилає.
 */
function Attachment({ order, message, onOpen }) {
  const [src, setSrc] = useState(null)
  const [failed, setFailed] = useState('')

  useEffect(() => {
    if (message.file_kind !== 'photo') return undefined
    let alive = true
    let created = null
    api.chatFile(order, message.id)
      .then((url) => {
        created = url
        if (alive) setSrc(url)
        else URL.revokeObjectURL(url)
      })
      .catch((err) => alive && setFailed(err.message))
    return () => {
      alive = false
      // Обʼєктні посилання тримають файл у памʼяті вкладки, доки їх не
      // звільнити. У довгій стрічці це десятки мегабайт.
      if (created) URL.revokeObjectURL(created)
    }
  }, [order, message.id, message.file_kind])

  if (failed) return <div className="bubble-head">{failed}</div>
  if (message.file_kind !== 'photo') {
    return <div className="bubble-head">Вкладення: {message.file_name || message.file_kind}</div>
  }
  if (!src) return <div className="skeleton thumb" />

  return (
    <button className="thumb-open" onClick={() => onOpen(src)}>
      <img className="thumb" src={src} alt={message.file_name || 'Вкладення'} />
    </button>
  )
}

export function ChatRoom({ config, order, onBack }) {
  const [messages, setMessages] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [sendError, setSendError] = useState('')
  // Відкрите на весь екран фото. Окремим станом, а не станом картинки:
  // з нього треба виходити системною кнопкою «назад», і знати про це
  // має екран, а не вкладення.
  const [viewing, setViewing] = useState(null)
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

  // Менеджер відповідає з панелі, тож стрічку доводиться підтягувати самим
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

  const attach = async (event) => {
    const file = event.target.files?.[0]
    // Скидаємо одразу: інакше повторний вибір того самого файлу не
    // викличе подію, і людині здасться, що кнопка зламалась.
    event.target.value = ''
    if (!file) return

    setUploading(true)
    setSendError('')
    try {
      const data = await api.chatPhoto(order.id, file)
      setMessages(data.messages)
      notify('success')
    } catch (err) {
      setSendError(err.message)
      notify('error')
    } finally {
      setUploading(false)
    }
  }

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
      {viewing && (
        // Дотик будь-де закриває: у переглядачі фото це очікувана дія,
        // і окремий хрестик у куті лише додає, що промахнутись повз.
        <div className="viewer" onClick={() => setViewing(null)} role="presentation">
          <img src={viewing} alt="Вкладення" />
        </div>
      )}
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
            Напишіть питання — менеджер відповість сюди й у чат із ботом.
          </p>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`bubble ${m.direction === 'in' ? 'mine' : ''}`}>
              <div className="bubble-head">
                {m.direction === 'in' ? 'Ви' : m.author || 'Менеджер'} · {clock(m.created_at)}
              </div>
              {m.text && <div className="bubble-text">{m.text}</div>}
              {m.file_kind && (
                <Attachment order={order.id} message={m} onOpen={setViewing} />
              )}
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>

      {sendError && <div className="banner warn">{sendError}</div>}

      <div className="chat-compose">
        {/* Скріншот квитанції — рівно те, чого просить текст після
            оформлення. Досі вітрина це обіцяла, а надіслати не давала:
            вкладення приймала тільки розмова з ботом. */}
        <label className="attach" aria-label="Додати фото">
          {uploading ? '…' : '📎'}
          <input
            type="file"
            accept="image/*"
            hidden
            onChange={attach}
            disabled={uploading}
          />
        </label>
        {/* Той самий компонент, що й у формі замовлення. Тут його
            бракувало найбільше: людина писала менеджеру наосліп — у полі
            не було видно жодної літери, поки не перейдеш кудись інде. */}
        <Field
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="Повідомлення менеджеру"
        />
        {/* Кругла кнопка зі стрілкою замість підпису «Надіслати».
            Раніше тут стояв каталожний клас .add, а він на всю ширину
            колонки — кнопка не вміщалася в рядок і перестрибувала під
            скріпку з полем. Та й у месенджерах цю дію впізнають за
            формою й стрілкою, а не за словом: підпис забирав пів рядка,
            який потрібен самому повідомленню. */}
        <button
          className="send"
          onClick={send}
          disabled={busy || !text.trim()}
          aria-label="Надіслати"
        >
          {busy ? '·' : '↑'}
        </button>
      </div>
    </div>
  )
}
