import { money } from '../money'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

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

const PAGE_SIZE = 200

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
  const open = (orders || []).filter((o) => o.can_chat === true)

  if (open.length === 0) {
    return (
      <div className="empty">
        <h2>Доступних чатів зараз немає</h2>
        <p>Чат доступний під час виконання та ще 7 днів після завершення замовлення. Для інших питань зверніться до загальної підтримки.</p>
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
              {money(o.total)} {config.currency}
            </span>
          </div>
          <div className="order-meta">
            <span className={`status-pill status-${o.status}`}>
              {o.status_label || STATUS[o.status] || o.status}
            </span>
            <span className="hint num">{o.chat_until ? `Чат до ${clock(o.chat_until)}` : clock(o.created_at)}</span>
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
  const [viewing, setViewing] = useState(null)
  const [error, setError] = useState('')
  const [hasOlder, setHasOlder] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [olderError, setOlderError] = useState('')
  const [access, setAccess] = useState(order)
  const logRef = useRef(null)
  const bottom = useRef(null)
  const sendingRef = useRef(false)
  const uploadingRef = useRef(false)
  const lastMessageIdRef = useRef(0)
  const pollInFlightRef = useRef(false)
  const olderInFlightRef = useRef(false)
  const pollCyclesRef = useRef(0)
  const roomIdRef = useRef(order.id)
  const aliveRef = useRef(true)
  const anchorRef = useRef(null)
  const stickBottomRef = useRef(true)
  const acknowledgedRef = useRef(new Set())
  const ackInFlightRef = useRef(false)

  const rememberScroll = () => {
    const el = logRef.current
    if (!el) return
    const edge = el.getBoundingClientRect().top
    const first = [...el.querySelectorAll('[data-message-id]')].find(node => node.getBoundingClientRect().bottom > edge)
    anchorRef.current = first ? { id: first.dataset.messageId, offset: first.getBoundingClientRect().top - edge } : null
  }

  const load = useCallback(async (silent = false, initial = false) => {
    if (pollInFlightRef.current) return
    pollInFlightRef.current = true
    try {
      const requestedOrderId = order.id
      // Delta pages advance in ascending ID order, including >200 new replies.
      // Never jump to the last page during reconnect: that would create holes.
      const incoming = await api.chat.list(requestedOrderId, initial ? null : lastMessageIdRef.current || null)
      if (!aliveRef.current || roomIdRef.current !== requestedOrderId) return
      if (initial) setHasOlder(incoming.length >= PAGE_SIZE)
      if (incoming.length) {
        lastMessageIdRef.current = Math.max(lastMessageIdRef.current, ...incoming.map(m => Number(m.id)))
        if (!stickBottomRef.current) rememberScroll()
      }
      setMessages(current => mergeMessages(current || [], incoming))
      setError('')
      try {
        const policy = await api.chat.access(requestedOrderId)
        if (aliveRef.current && roomIdRef.current === requestedOrderId) setAccess(policy)
      } catch { /* Send endpoint still enforces the current server policy. */ }
    } catch (err) {
      if (aliveRef.current && !silent) setError(err.message)
    } finally {
      pollInFlightRef.current = false
    }
  }, [order.id])

  useEffect(() => {
    aliveRef.current = true
    roomIdRef.current = order.id
    load(false, true)
    return () => { aliveRef.current = false }
  }, [load])

  useEffect(() => { setAccess(order) }, [order])

  const loadOlder = async () => {
    if (olderInFlightRef.current || !hasOlder || !messages?.length) return
    olderInFlightRef.current = true
    setLoadingOlder(true)
    setOlderError('')
    try {
      const older = await api.chat.older(order.id, messages[0].id, PAGE_SIZE)
      if (!aliveRef.current) return
      rememberScroll()
      stickBottomRef.current = false
      setHasOlder(older.length >= PAGE_SIZE)
      setMessages(current => mergeMessages(current, older))
    } catch (err) {
      if (aliveRef.current) setOlderError(err.message)
    } finally {
      olderInFlightRef.current = false
      if (aliveRef.current) setLoadingOlder(false)
    }
  }

  useLayoutEffect(() => {
    const el = logRef.current
    if (!el || messages === null) return
    const anchor = anchorRef.current
    if (anchor) {
      const node = el.querySelector(`[data-message-id="${anchor.id}"]`)
      if (node) el.scrollTop += node.getBoundingClientRect().top - el.getBoundingClientRect().top - anchor.offset
      anchorRef.current = null
    } else if (stickBottomRef.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages, hasOlder])

  // ACK only bubbles that intersect the visible conversation. Hidden tabs,
  // old pages and newly fetched offscreen replies cannot create read receipts.
  useEffect(() => {
    const el = logRef.current
    if (!el || !messages || viewing) return undefined
    let stopped = false
    let retry = null
    const ackVisible = async () => {
      if (stopped || document.hidden || ackInFlightRef.current || navigator.onLine === false) return
      const root = el.getBoundingClientRect()
      const ids = [...el.querySelectorAll('[data-direction="out"]')].filter(node => {
        const rect = node.getBoundingClientRect()
        return rect.bottom > Math.max(root.top, 0) && rect.top < Math.min(root.bottom, window.innerHeight)
      }).map(node => Number(node.dataset.messageId)).filter(id => !acknowledgedRef.current.has(id))
      if (!ids.length) return
      ackInFlightRef.current = true
      try {
        for (let i = 0; i < ids.length; i += 500) {
          const batch = ids.slice(i, i + 500)
          await api.chat.read(order.id, batch)
          batch.forEach(id => acknowledgedRef.current.add(id))
        }
      } catch { /* Retry visible IDs; failure never marks them locally as read. */ }
      finally {
        ackInFlightRef.current = false
        if (!stopped) retry = window.setTimeout(ackVisible, 5000)
      }
    }
    const observer = new IntersectionObserver(ackVisible, { root: el })
    el.querySelectorAll('[data-direction="out"]').forEach(node => observer.observe(node))
    el.addEventListener('scroll', ackVisible)
    document.addEventListener('visibilitychange', ackVisible)
    window.addEventListener('online', ackVisible)
    ackVisible()
    return () => {
      stopped = true
      clearTimeout(retry)
      observer.disconnect()
      el.removeEventListener('scroll', ackVisible)
      document.removeEventListener('visibilitychange', ackVisible)
      window.removeEventListener('online', ackVisible)
    }
  }, [messages, order.id, viewing])

  // Тихе live-оновлення. Hidden/offline вкладка не робить запитів; після
  // повернення/відновлення мережі синхронізуємося одразу.
  useEffect(() => {
    let stopped = false
    let timer = null
    const visibleAndOnline = () => !document.hidden && navigator.onLine !== false
    const clearTimer = () => {
      if (timer !== null) {
        clearTimeout(timer)
        timer = null
      }
    }
    const schedule = () => {
      clearTimer()
      if (!stopped && visibleAndOnline()) timer = window.setTimeout(poll, 5000)
    }
    const poll = async () => {
      if (stopped || !visibleAndOnline()) return
      pollCyclesRef.current += 1
      await load(true)
      schedule()
    }
    const wake = () => {
      clearTimer()
      if (visibleAndOnline()) poll()
    }
    schedule()
    document.addEventListener('visibilitychange', wake)
    window.addEventListener('focus', wake)
    window.addEventListener('online', wake)
    return () => {
      stopped = true
      clearTimer()
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('focus', wake)
      window.removeEventListener('online', wake)
    }
  }, [load])

  const attach = async (event) => {
    const file = event.target.files?.[0]
    // Скидаємо одразу: інакше повторний вибір того самого файлу не
    // викличе подію, і людині здасться, що кнопка зламалась.
    event.target.value = ''
    if (!file || uploadingRef.current || !access.can_chat) return

    uploadingRef.current = true
    setUploading(true)
    setSendError('')
    try {
      const data = await api.chatPhoto(order.id, file)
      if (!aliveRef.current) return
      stickBottomRef.current = true
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
    if (!body || sendingRef.current || !access.can_chat) return
    sendingRef.current = true
    setBusy(true)
    setError('')
    try {
      const sent = await api.chat.send(order.id, body)
      if (!aliveRef.current) return
      stickBottomRef.current = true
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
        <p>{order.status_label || STATUS[order.status] || order.status} · історія зберігається</p>
      </div>

      {error && <div className="banner warn">{error} <button className="secondary" onClick={() => load(false, messages === null)}>Повторити</button></div>}
      {access.can_chat && access.chat_until && <p className="hint chat-policy">Писати менеджеру можна до {clock(access.chat_until)}.</p>}
      {!access.can_chat && <div className="banner warn">Чат замовлення закрито. Історія доступна; для допомоги зверніться до загальної підтримки через /ask у боті.</div>}

      <div className="chat-log" ref={logRef} onScroll={() => {
        const el = logRef.current
        stickBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
      }}>
        {messages !== null && (hasOlder
          ? <button className="secondary chat-history" onClick={loadOlder} disabled={loadingOlder}>{loadingOlder ? 'Завантажуємо…' : 'Раніші повідомлення'}</button>
          : <p className="hint chat-history">Початок історії</p>)}
        {olderError && <div className="banner warn">{olderError} <button className="secondary" onClick={loadOlder}>Повторити</button></div>}
        {messages === null ? (
          <div className="skeleton skeleton-line" />
        ) : messages.length === 0 ? (
          <p className="hint chat-empty">
            Напишіть питання — менеджер відповість сюди й у чат із ботом.
          </p>
        ) : (
          messages.map((m) => (
            <div key={m.id} data-message-id={m.id} data-direction={m.direction} className={`bubble ${m.direction === 'in' ? 'mine' : ''}`}>
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
            disabled={uploading || !access.can_chat}
          />
        </label>
        {/* Той самий компонент, що й у формі замовлення. Тут його
            бракувало найбільше: людина писала менеджеру наосліп — у полі
            не було видно жодної літери, поки не перейдеш кудись інде. */}
        <Field
          value={text}
          disabled={!access.can_chat}
          maxLength={2000}
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
          disabled={busy || !text.trim() || !access.can_chat}
          aria-label="Надіслати"
        >
          {busy ? '·' : '↑'}
        </button>
      </div>
    </div>
  )
}
