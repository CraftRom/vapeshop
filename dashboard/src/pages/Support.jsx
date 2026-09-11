import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, getToken } from '../api'
import { Empty, ErrorBar, Loading, dateTime, useToast } from '../components/ui'
import { useVisiblePolling } from '../components/useVisiblePolling'

const FILE_LABEL = {
  photo: 'Фото', document: 'Документ', video: 'Відео', voice: 'Голосове',
}

function clientName(thread) {
  const user = thread?.user || {}
  return user.first_name || (user.username ? `@${user.username}` : '') || `Telegram ${user.tg_id || ''}`
}

function clientMeta(thread) {
  const user = thread?.user || {}
  return [user.username ? `@${user.username}` : null, user.phone, user.tg_id ? `ID ${user.tg_id}` : null]
    .filter(Boolean).join(' · ')
}

function Attachment({ threadId, message }) {
  const [url, setUrl] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let revoked = null
    let cancelled = false
    fetch(api.support.fileUrl(threadId, message.id), {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((blob) => {
        if (cancelled) return
        revoked = URL.createObjectURL(blob)
        setUrl(revoked)
      })
      .catch((err) => !cancelled && setFailed(err.message === '410' ? 'gone' : true))
    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [threadId, message.id])

  const label = FILE_LABEL[message.file_kind] || 'Файл'
  if (failed) {
    return <div className="faint support-file-state">{failed === 'gone' ? `${label} більше недоступний` : `${label} не завантажився`}</div>
  }
  if (!url) return <div className="faint support-file-state">{label} завантажується…</div>

  if (message.file_kind === 'photo') {
    return (
      <a href={url} target="_blank" rel="noreferrer">
        <img className="bubble-photo" src={url} alt={label} />
      </a>
    )
  }
  if (message.file_kind === 'voice') return <audio controls src={url} className="support-media" />
  if (message.file_kind === 'video') return <video controls src={url} className="bubble-photo" />
  return (
    <a href={url} download={message.file_name || 'file'} className="btn ghost small support-file-link">
      ↓ {message.file_name || label}
    </a>
  )
}

function ThreadRow({ thread, active, onClick }) {
  return (
    <button
      type="button"
      className={`support-thread ${active ? 'active' : ''}`}
      onClick={onClick}
    >
      <div className="support-thread-top">
        <strong>{clientName(thread)}</strong>
        <span className="support-thread-time">
          {thread.last_message_at ? dateTime(thread.last_message_at) : ''}
        </span>
      </div>
      <div className="support-thread-bottom">
        <span className="faint support-thread-meta">{clientMeta(thread) || 'Без контактів'}</span>
        <span className="support-thread-flags">
          {thread.status === 'closed' && <span className="support-state closed">Закрито</span>}
          {thread.unread_count > 0 && <span className="badge">{thread.unread_count}</span>}
        </span>
      </div>
    </button>
  )
}

function Conversation({ thread, messages, onBack, onRefresh, onStatus }) {
  const notify = useToast()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const bottom = useRef(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages, thread?.id])

  const send = async () => {
    const body = text.trim()
    if (!body || !thread) return
    setBusy(true)
    try {
      const result = await api.support.send(thread.id, body)
      setText('')
      if (!result.delivered) notify(result.warning || 'Telegram не підтвердив доставку', 'bad')
      await onRefresh(true)
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  const toggleStatus = async () => {
    if (!thread) return
    setBusy(true)
    try {
      const next = thread.status === 'open' ? 'closed' : 'open'
      await api.support.setStatus(thread.id, next)
      notify(next === 'closed' ? 'Звернення закрито' : 'Звернення повернуто в роботу')
      await onStatus(next)
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  if (!thread) {
    return (
      <div className="support-conversation-empty">
        <Empty title="Оберіть звернення">
          Ліворуч показані клієнти, які написали через команду /ask.
        </Empty>
      </div>
    )
  }

  const user = thread.user || {}
  return (
    <section className="support-conversation">
      <header className="support-chat-head">
        <button className="btn ghost small support-mobile-back" onClick={onBack}>← Назад</button>
        <div className="support-chat-person">
          <div className="support-chat-title-row">
            <h2>{clientName(thread)}</h2>
            <span className={`support-state ${thread.status === 'closed' ? 'closed' : 'open'}`}>
              {thread.status === 'closed' ? 'Закрито' : 'В роботі'}
            </span>
          </div>
          <div className="faint support-chat-meta">
            {user.username && <span>@{user.username}</span>}
            {user.phone && <a href={`tel:${user.phone}`}>{user.phone}</a>}
            {user.tg_id && <span>Telegram ID {user.tg_id}</span>}
            {user.bot_reachable === false && <span className="support-unreachable">бот недоступний</span>}
          </div>
        </div>
        <button
          className={`btn small ${thread.status === 'open' ? 'ghost' : ''}`}
          onClick={toggleStatus}
          disabled={busy}
        >
          {thread.status === 'open' ? 'Закрити' : 'Відкрити знову'}
        </button>
      </header>

      <div className="support-chat-log">
        {messages.length === 0 ? (
          <div className="support-no-messages faint">Повідомлень ще немає.</div>
        ) : messages.map((message) => (
          <div
            key={message.id}
            className={`support-bubble ${message.direction === 'out' ? 'mine' : ''}`}
          >
            <div className="bubble-head faint">
              {message.direction === 'out' ? message.author || 'Менеджер' : message.author || 'Клієнт'}
              {' · '}{message.created_at ? dateTime(message.created_at) : ''}
            </div>
            {message.text && <div className="bubble-text">{message.text}</div>}
            {message.file_kind && <Attachment threadId={thread.id} message={message} />}
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <div className="support-compose">
        {thread.status === 'closed' && (
          <div className="support-compose-note">
            Відповідь автоматично поверне звернення у статус «В роботі».
          </div>
        )}
        <div className="support-compose-row">
          <textarea
            className="input"
            rows={2}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Напишіть відповідь клієнту…"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            }}
          />
          <button className="btn" onClick={send} disabled={busy || !text.trim()}>
            {busy ? 'Надсилаємо…' : 'Надіслати'}
          </button>
        </div>
        <div className="faint support-compose-hint">Enter — надіслати · Shift+Enter — новий рядок</div>
      </div>
    </section>
  )
}

export default function Support() {
  const [status, setStatus] = useState('open')
  const [query, setQuery] = useState('')
  const [threads, setThreads] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [thread, setThread] = useState(null)
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadThreads = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const data = await api.support.list(status)
      setThreads(data)
      setError('')

      // На широкому екрані одразу відкриваємо перше звернення. На телефоні
      // список має лишитись списком — автоматичний перехід у чат там заважає.
      if (!selectedId && data.length && !window.matchMedia('(max-width: 760px)').matches) {
        setSelectedId(data[0].id)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [status, selectedId])

  const loadConversation = useCallback(async (markRead = false) => {
    if (!selectedId) {
      setThread(null)
      setMessages([])
      return
    }
    try {
      const [freshThread, freshMessages] = await Promise.all([
        api.support.get(selectedId),
        api.support.messages(selectedId, markRead),
      ])
      setThread(freshThread)
      setMessages(freshMessages)
      if (markRead) {
        setThreads((items) => items.map((item) => (
          item.id === selectedId ? { ...item, unread_count: 0 } : item
        )))
      }
    } catch (err) {
      setError(err.message)
    }
  }, [selectedId])

  useEffect(() => {
    loadThreads()
  }, [status]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedId) return
    loadConversation(true)
  }, [selectedId, loadConversation])

  const pollSupport = useCallback(async () => {
    await loadThreads(true)
    if (selectedId) await loadConversation(false)
  }, [loadThreads, loadConversation, selectedId])
  useVisiblePolling(pollSupport, 10000)

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return threads
    return threads.filter((item) => {
      const user = item.user || {}
      return [user.first_name, user.username, user.phone, user.tg_id]
        .filter(Boolean).some((value) => String(value).toLowerCase().includes(needle))
    })
  }, [threads, query])

  const select = (id) => {
    setSelectedId(id)
    setError('')
  }

  const statusChanged = async (next) => {
    setThread((current) => current ? { ...current, status: next } : current)
    await loadThreads(true)
    if (status !== 'all' && next !== status) {
      setSelectedId(null)
      setThread(null)
      setMessages([])
    } else {
      await loadConversation(false)
    }
  }

  return (
    <>
      <div className="page-head support-page-head">
        <div>
          <h1>Підтримка</h1>
          <p>Загальні питання й технічні звернення клієнтів із Telegram через /ask</p>
        </div>
      </div>

      <ErrorBar error={error} />

      <div className={`support-layout ${selectedId ? 'has-selection' : ''}`}>
        <aside className="support-inbox card">
          <div className="support-filters">
            <div className="support-tabs" role="tablist" aria-label="Статус звернень">
              {[
                ['open', 'В роботі'],
                ['closed', 'Закриті'],
                ['all', 'Усі'],
              ].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={`btn small ${status === key ? '' : 'ghost'}`}
                  onClick={() => {
                    setStatus(key)
                    setSelectedId(null)
                    setThread(null)
                    setMessages([])
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            <input
              className="input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ім’я, @username, телефон або Telegram ID"
            />
          </div>

          <div className="support-thread-list">
            {loading ? <Loading rows={5} /> : filtered.length === 0 ? (
              <Empty title="Звернень немає">
                Нові повідомлення з’являться тут після того, як клієнт введе /ask.
              </Empty>
            ) : filtered.map((item) => (
              <ThreadRow
                key={item.id}
                thread={item}
                active={item.id === selectedId}
                onClick={() => select(item.id)}
              />
            ))}
          </div>
        </aside>

        <Conversation
          thread={thread}
          messages={messages}
          onBack={() => {
            setSelectedId(null)
            setThread(null)
            setMessages([])
          }}
          onRefresh={loadConversation}
          onStatus={statusChanged}
        />
      </div>
    </>
  )
}
