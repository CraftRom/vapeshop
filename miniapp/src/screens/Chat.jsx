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

function mergeMessages(current, incoming) {
  const map = new Map()
  for (const item of current || []) map.set(item.id, item)
  for (const item of incoming || []) map.set(item.id, item)
  return [...map.values()].sort((a, b) => Number(a.id) - Number(b.id))
}

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
        <h2>Активних замовлень зараз немає</h2>
        <p>Щойно оформите замовлення, тут з’явиться окрема розмова з менеджером.</p>
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
          <div className="order-meta">
            <span className={`status-pill status-${o.status}`}>
              {STATUS[o.status] || o.status}
            </span>
            <span className="hint num">{clock(o.created_at)}</span>
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
  const sendingRef = useRef(false)
  const uploadingRef = useRef(false)
  const lastMessageIdRef = useRef(0)
  const pollInFlightRef = useRef(false)
  const pollCyclesRef = useRef(0)
  const roomIdRef = useRef(order.id)

  const load = useCallback(
    async (silent = false, full = false) => {
      if (pollInFlightRef.current) return
      pollInFlightRef.current = true
      try {
        const requestedOrderId = order.id
        // Зазвичай забираємо лише нові повідомлення. Раз на шість циклів
        // робимо повний reconcile: це лікує рідкісний пропуск після reconnect
        // і не ганяє всю історію кожні 5 секунд.
        const afterId = full ? null : lastMessageIdRef.current
        const incoming = await api.chat.list(requestedOrderId, afterId || null)
        if (roomIdRef.current !== requestedOrderId) return
        if (incoming?.length) {
          lastMessageIdRef.current = Math.max(
            lastMessageIdRef.current,
            ...incoming.map((item) => Number(item.id) || 0),
          )
        }
        setMessages((current) => (
          current === null || full ? mergeMessages(current || [], incoming) : mergeMessages(current, incoming)
        ))
        setError('')
      } catch (err) {
        if (!silent) setError(err.message)
      } finally {
        pollInFlightRef.current = false
      }
    },
    [order.id],
  )

  useEffect(() => {
    roomIdRef.current = order.id
    lastMessageIdRef.current = 0
    pollCyclesRef.current = 0
    setMessages(null)
    load(false, true)
  }, [load])

  // Тихе live-оновлення. Hidden/offline вкладка не робить запитів; після
  // повернення/відновлення мережі синхронізуємося одразу.
  useEffect(() => {
    const poll = () => {
      if (document.hidden || !navigator.onLine) return
      pollCyclesRef.current += 1
      load(true, pollCyclesRef.current % 6 === 0)
    }
    const timer = setInterval(poll, 5000)
    const wake = () => poll()
    document.addEventListener('visibilitychange', wake)
    window.addEventListener('online', wake)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('online', wake)
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
    if (!file || uploadingRef.current) return

    uploadingRef.current = true
    setUploading(true)
    setSendError('')
    try {
      const data = await api.chatPhoto(order.id, file)
      setMessages((current) => mergeMessages(current, data.messages))
      notify('success')
    } catch (err) {
      setSendError(err.message)
      notify('error')
    } finally {
      uploadingRef.current = false
      setUploading(false)
    }
  }

  const send = async () => {
    const body = text.trim()
    if (!body || sendingRef.current) return
    sendingRef.current = true
    setBusy(true)
    setError('')
    try {
      const sent = await api.chat.send(order.id, body)
      setMessages((prev) => mergeMessages(prev, [sent]))
      setText('')
      haptic('light')
    } catch (err) {
      setError(err.message)
    } finally {
      sendingRef.current = false
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
      <div className="head chat-head">
        <button className="back" onClick={onBack}>
          Замовлення
        </button>
        <h1>Замовлення №{order.id}</h1>
        <p>{STATUS[order.status] || order.status}</p>
      </div>

      {error && <div className="banner warn">{error}</div>}

      <div className="chat-log">
        {messages === null ? (
          <div className="skeleton skeleton-line" />
        ) : messages.length === 0 ? (
          <p className="hint chat-empty">
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
