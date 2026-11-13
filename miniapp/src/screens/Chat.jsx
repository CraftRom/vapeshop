import { money } from '../money'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { api } from '../api'
import { supportRequest, confirmSupportRequest } from '../supportRequests'
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
        <p>Оберіть замовлення, щоб відкрити його чат.</p>
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
function Attachment({ order, message, onOpen, support = false }) {
  const kind = message.file_kind
  const isPdf = kind === 'document' && /\.pdf$/i.test(message.file_name || '')
  const [previewPdf, setPreviewPdf] = useState(false)
  const [src, setSrc] = useState(null)
  const [failed, setFailed] = useState('')
  const [loading, setLoading] = useState(false)
  const [codecError, setCodecError] = useState(false)
  const pending = useRef(false)
  const objectUrl = useRef(null)
  const active = useRef(true)

  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    }
  }, [])

  const fetchMedia = useCallback(async () => {
    if (pending.current || objectUrl.current) return
    pending.current = true
    setLoading(true)
    setFailed('')
    try {
      // Download via signed first-party API, not public Telegram URLs.
      // Video/voice/document bytes are loaded ONLY after the user asks.
      const url = await api.chatFile(order, message.id, support)
      if (active.current) {
        objectUrl.current = url
        setSrc(url)
      } else URL.revokeObjectURL(url)
    } catch (err) {
      if (active.current) setFailed(err.message || 'Не вдалося завантажити файл')
    } finally {
      pending.current = false
      if (active.current) setLoading(false)
    }
  }, [order, message.id, support])

  useEffect(() => {
    if (kind === 'photo') fetchMedia()
  }, [kind, fetchMedia])

  const label = kind === 'video' ? 'Відео' : kind === 'voice' ? 'Голосове' : kind === 'photo' ? 'Фото' : isPdf ? 'PDF' : 'Документ'
  if (failed) return (
    <div className="chat-media-state" role="alert">
      <span>{label}: {failed}</span>
      <button className="secondary" type="button" onClick={fetchMedia}>Повторити</button>
    </div>
  )
  if (kind === 'photo') {
    if (!src) return <div className="skeleton thumb" role="status" aria-label="Завантаження фото" />
    return <button type="button" className="thumb-open" onClick={() => onOpen(src)} aria-label="Відкрити фото">
      <img className="thumb" src={src} alt={message.file_name || 'Фото'} loading="lazy" />
    </button>
  }
  if (!src) return (
    <button type="button" className="chat-media-action" onClick={fetchMedia} disabled={loading}>
      <span aria-hidden="true">{kind === 'video' ? '▶' : kind === 'voice' ? '♫' : '↓'}</span>
      {loading ? 'Завантажуємо вкладення…' : kind === 'video' ? 'Переглянути відео' : kind === 'voice' ? 'Слухати голосове' : isPdf ? `Відкрити PDF · ${message.file_name || 'Документ'}` : `Завантажити ${message.file_name || 'документ'}`}
    </button>
  )
  if (kind === 'video') return (
    <div className="chat-media-player">
      <video src={src} controls preload="metadata" playsInline className="chat-video" aria-label={message.file_name || 'Відео в чаті'} onError={() => setCodecError(true)}>
        Ваш браузер не підтримує це відео.
      </video>
      {codecError && <p className="hint chat-codec-hint">Цей формат або кодек не підтримується вашим браузером. Спробуйте зберегти відео.</p>}
      <a href={src} download={message.file_name || 'video.mp4'} className="chat-media-download">Зберегти відео</a>
    </div>
  )
  if (isPdf) return (
    <div className="chat-pdf">
      <div className="chat-pdf-actions">
        <button type="button" className="secondary" onClick={() => setPreviewPdf(v => !v)} aria-expanded={previewPdf}>
          {previewPdf ? 'Сховати PDF' : 'Переглянути PDF'}
        </button>
        <a href={src} download={message.file_name || 'document.pdf'} className="chat-media-download">Завантажити PDF</a>
      </div>
      {previewPdf && <iframe src={src} sandbox="allow-scripts" title={`PDF: ${message.file_name || 'Документ'}`} className="chat-pdf-frame" loading="lazy" referrerPolicy="no-referrer" />}
      <p className="hint chat-pdf-hint">Якщо перегляд недоступний у Telegram, збережіть файл і відкрийте його в переглядачі PDF.</p>
    </div>
  )
  if (kind === 'voice') return <audio src={src} controls preload="metadata" className="chat-audio" />
  return <a href={src} download={message.file_name || 'attachment'} className="chat-media-download">Завантажити {message.file_name || 'документ'}</a>
}


export function ChatRoom({ config, order, onBack, support = false, draft = null, onSupport }) {
  const transport = useMemo(() => support ? {
    list: async(id, after) => (await api.support.messages(id, after == null ? {} : {after_id:after})).items,
    older: async(id, before, limit) => (await api.support.messages(id,{before_id:before,limit})).items,
    access: async id => { const thread=await api.support.get(id);return {...thread,can_chat:thread.status==='open'} },
    send: api.support.send,
  } : api.chat, [support])
  const [messages, setMessages] = useState(null)
  const [text, setText] = useState(draft?.text || '')
  const textRef = useRef(draft?.text || '')
  const changeText = value => {
    textRef.current=value;setText(value)
    if(draft){draft.text=value;draft.revision++;draft.listeners.forEach(sync=>sync())}
  }
  useEffect(()=>{
    if(!draft)return undefined
    const sync=()=>{textRef.current=draft.text;setText(draft.text)}
    draft.listeners.add(sync);sync()
    return()=>draft.listeners.delete(sync)
  },[draft])
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
      const incoming = await transport.list(requestedOrderId, initial ? null : lastMessageIdRef.current)
      if (!aliveRef.current || roomIdRef.current !== requestedOrderId) return
      if (initial) setHasOlder(incoming.length >= PAGE_SIZE)
      if (incoming.length) {
        lastMessageIdRef.current = Math.max(lastMessageIdRef.current, ...incoming.map(m => Number(m.id)))
        if (!stickBottomRef.current) rememberScroll()
      }
      setMessages(current => mergeMessages(current || [], incoming))
      setError('')
      try {
        const policy = await transport.access(requestedOrderId)
        if (aliveRef.current && roomIdRef.current === requestedOrderId) setAccess(policy)
      } catch { /* Send endpoint still enforces the current server policy. */ }
    } catch (err) {
      if (aliveRef.current && (support || !silent)) setError(err.message)
    } finally {
      pollInFlightRef.current = false
    }
  }, [order.id, transport, support])

  useEffect(() => {
    aliveRef.current = true
    roomIdRef.current = order.id
    load(false, true)
    return () => { aliveRef.current = false }
  }, [load])

  useEffect(() => { if(!support)setAccess(order) }, [order,support])

  const loadOlder = async () => {
    if (olderInFlightRef.current || !hasOlder || !messages?.length) return
    olderInFlightRef.current = true
    setLoadingOlder(true)
    setOlderError('')
    try {
      const older = await transport.older(order.id, messages[0].id, PAGE_SIZE)
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
    if (support || !el || !messages || viewing) return undefined
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
  }, [messages, order.id, viewing, support])

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
      const video = file.type === 'video/mp4' ||
        ((!file.type || file.type === 'application/octet-stream') && /\.mp4$/i.test(file.name))
      const pdf = file.type === 'application/pdf' || file.type === 'application/x-pdf' ||
        ((!file.type || file.type === 'application/octet-stream') && /\.pdf$/i.test(file.name))
      if (!video && !pdf && !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
        throw new Error('Виберіть фото JPEG/PNG/WebP, відео MP4 або PDF')
      }
      if (file.size > (video || pdf ? 15 : 8) * 1024 * 1024) {
        throw new Error(video ? 'Відео має бути до 15 МБ' : pdf ? 'PDF має бути до 15 МБ' : 'Фото має бути до 8 МБ')
      }
      const data = await api.chatMedia(order.id, file, support)
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
    const submitted = textRef.current
    const submittedRevision = draft?.revision
    const body = submitted.trim()
    if (!body || sendingRef.current || !access.can_chat) return
    sendingRef.current = true
    setBusy(true)
    setError('')
    try {
      const attempt = support ? supportRequest(order.id,body) : null
      const sent = await transport.send(order.id, body, attempt?.request_id)
      if (attempt) confirmSupportRequest(order.id,attempt.request_id)
      if(draft && draft.revision===submittedRevision){draft.text='';draft.revision++;draft.listeners.forEach(sync=>sync())}
      if (!aliveRef.current) return
      stickBottomRef.current = true
      setMessages((prev) => mergeMessages(prev, [sent]))
      if(textRef.current===submitted)changeText('')
      haptic('light')
    } catch (err) {
      if(aliveRef.current){setError(err.message);if(support && err.status===409)load(true)}
    } finally {
      sendingRef.current = false
      if(aliveRef.current)setBusy(false)
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
          {support?'Звернення':'Замовлення'}
        </button>
        <h1>{support?'Звернення':'Замовлення'} №{order.id}</h1>
        <p>{support?(access.status==='closed'?'Завершене звернення':'Розмова з підтримкою'):(order.status_label || STATUS[order.status] || order.status)} · історія зберігається</p>
        {support && access.can_chat && <button className="secondary" disabled={busy} onClick={async()=>{
          if(sendingRef.current || !window.confirm('Завершити це звернення? Історія залишиться доступною.'))return
          sendingRef.current=true;setBusy(true)
          try{const thread=await api.support.close(order.id);if(aliveRef.current)setAccess({...thread,can_chat:false})}
          catch(err){if(aliveRef.current)setError(err.message)}
          finally{sendingRef.current=false;if(aliveRef.current)setBusy(false)}
        }}>Завершити звернення</button>}
      </div>

      {error && <div className="banner warn">{error} <button className="secondary" onClick={() => load(false, messages === null)}>Оновити чат</button></div>}
      {access.can_chat && access.chat_until && <p className="hint chat-policy">Писати менеджеру можна до {clock(access.chat_until)}.</p>}
      {!access.can_chat && <div className="banner warn">{support?'Звернення завершено. Історія доступна; для нового питання поверніться до списку й створіть нове звернення.':'Чат замовлення закрито. Історія доступна; для допомоги зверніться до загальної підтримки.'}{!support && onSupport && <button className="secondary" onClick={onSupport}>Загальна підтримка</button>}</div>}

      <div className="chat-log" role="region" aria-label={support?"Переписка підтримки":"Переписка замовлення"} ref={logRef} onScroll={() => {
        const el = logRef.current
        stickBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
      }}>
        {messages !== null && (hasOlder
          ? <button className="secondary chat-history" onClick={loadOlder} disabled={loadingOlder}>{loadingOlder ? 'Завантажуємо…' : 'Раніші повідомлення'}</button>
          : <p className="hint chat-history">Початок історії</p>)}
        {olderError && <div className="banner warn">{olderError} <button className="secondary" onClick={loadOlder}>Завантажити раніші</button></div>}
        {messages === null ? (
          <div className="skeleton skeleton-line" />
        ) : messages.length === 0 ? (
          <p className="hint chat-empty">
            {access.can_chat
              ? 'Напишіть питання менеджеру. Його відповідь з’явиться в цьому чаті.'
              : 'У цьому чаті немає повідомлень.'}
          </p>
        ) : (
          messages.map((m) => (
            <div key={m.id} data-message-id={m.id} data-direction={m.direction} className={`bubble ${m.direction === 'in' ? 'mine' : ''}`}>
              <div className="bubble-head">
                {m.direction === 'in' ? 'Ви' : (support?'Підтримка':m.author || 'Менеджер')} · {clock(m.created_at)}
              </div>
              {m.text && <div className="bubble-text">{m.text}</div>}
              {m.file_kind && (
                <Attachment order={order.id} message={m} onOpen={setViewing} support={support} />
              )}
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>

      {sendError && <div className="banner warn" role="alert">{sendError}</div>}

      {uploading && <p className="hint chat-upload-state" role="status">Надсилаємо вкладення… Не закривайте чат.</p>}
      <div className="chat-compose">
        {/* Один вибір файлів для чату замовлення і підтримки: фото, MP4 або PDF. */}
        <label className="attach" aria-label="Додати фото, відео або PDF" title="Фото до 8 МБ, MP4/PDF до 15 МБ">
          {uploading ? '…' : '📎'}
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp,video/mp4,.mp4,application/pdf,.pdf"
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
          onChange={(e) => changeText(e.target.value)}
          onKeyDown={(e) => {if(e.key==='Enter' && !e.shiftKey && !e.nativeEvent.isComposing){e.preventDefault();send()}}}
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
