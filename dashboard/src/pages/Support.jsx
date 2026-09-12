import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, getToken } from '../api'
import { Empty, ErrorBar, Loading, dateTime, useToast } from '../components/ui'
import { useVisiblePolling } from '../components/useVisiblePolling'

const FILE_LABEL = {
  photo: 'Фото', document: 'Документ', video: 'Відео', voice: 'Голосове',
}

const EMPTY_STATS = { open: 0, closed: 0, total: 0, clients: 0, unread: 0 }

function clientName(thread) {
  const user = thread?.user || {}
  return user.first_name || (user.username ? `@${user.username}` : '') || `Telegram ${user.tg_id || ''}`
}

function clientMeta(thread) {
  const user = thread?.user || {}
  return [user.username ? `@${user.username}` : null, user.phone, user.tg_id ? `ID ${user.tg_id}` : null]
    .filter(Boolean).join(' · ')
}

function stamp(value) {
  if (!value) return 0
  const n = new Date(value).getTime()
  return Number.isFinite(n) ? n : 0
}

function closeDescription(thread, compact = false) {
  if (!thread || thread.status !== 'closed') return ''
  const when = thread.closed_at ? dateTime(thread.closed_at) : ''
  let who = 'Системою'
  if (thread.closed_by === 'client') who = 'Клієнтом'
  if (thread.closed_by === 'staff') who = thread.closed_by_name ? `Менеджером: ${thread.closed_by_name}` : 'Менеджером'

  let reason = ''
  if (thread.close_reason === 'done') reason = 'завершено клієнтом'
  if (thread.close_reason === 'manager') reason = 'завершено менеджером'
  if (thread.close_reason === 'order_switch') reason = 'клієнт перейшов до чату замовлення'
  if (thread.close_reason === 'deduplicate') reason = 'закрито під час виправлення дубльованих сесій'
  if (thread.close_reason === 'legacy') reason = 'історичне завершене звернення'

  if (compact) return [who, when].filter(Boolean).join(' · ')
  return [who, reason, when].filter(Boolean).join(' · ')
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

function SessionRow({ thread, active, onClick }) {
  return (
    <button
      type="button"
      className={`support-session ${active ? 'active' : ''}`}
      onClick={onClick}
    >
      <span className="support-session-main">
        <strong>Звернення #{thread.id}</strong>
        <span className={`support-state ${thread.status === 'closed' ? 'closed' : 'open'}`}>
          {thread.status === 'closed' ? 'Закрито' : 'В роботі'}
        </span>
      </span>
      <span className="support-session-side">
        <span className="faint">{thread.last_message_at ? dateTime(thread.last_message_at) : dateTime(thread.created_at)}</span>
        {thread.status === 'closed' && <span className="faint support-session-close">{closeDescription(thread, true)}</span>}
        {thread.unread_count > 0 && <span className="badge">{thread.unread_count}</span>}
      </span>
    </button>
  )
}

function ClientGroup({ group, selectedId, onSelect }) {
  return (
    <section className="support-client-group">
      <div className="support-client-head">
        <div className="support-client-identity">
          <strong>{clientName(group.threads[0])}</strong>
          <span className="faint support-thread-meta">{clientMeta(group.threads[0]) || 'Без контактів'}</span>
        </div>
        <div className="support-client-counters" aria-label="Статистика клієнта">
          <span title="Усього звернень">{group.threads.length} чат.</span>
          {group.openCount > 0 && <span className="support-mini-open">{group.openCount} відкрито</span>}
          {group.unread > 0 && <span className="badge">{group.unread}</span>}
        </div>
      </div>
      <div className="support-session-list">
        {group.threads.map((thread) => (
          <SessionRow
            key={thread.id}
            thread={thread}
            active={thread.id === selectedId}
            onClick={() => onSelect(thread.id)}
          />
        ))}
      </div>
    </section>
  )
}

function Conversation({ thread, messages, onBack, onRefresh, onStatus, onDelete }) {
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

  const closeSession = async () => {
    if (!thread || thread.status !== 'open') return
    const yes = window.confirm(
      `Закрити звернення #${thread.id}?\n\nСесію буде завершено для клієнта й менеджера. Історія залишиться незмінною. Для наступного питання клієнт створить нове звернення через /ask.`
    )
    if (!yes) return
    setBusy(true)
    try {
      const updated = await api.support.setStatus(thread.id, 'closed')
      if (updated?.closed_by === 'staff') {
        notify('Звернення закрито; історія збережена.')
      } else {
        notify(`Звернення вже було закрито. ${closeDescription(updated) || ''}`.trim())
      }
      await onStatus('closed')
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!thread || thread.status !== 'closed') return
    const yes = window.confirm(
      `Видалити звернення #${thread.id} назавжди?\n\nБуде стерто всю історію цього конкретного чату. Інші звернення клієнта залишаться.`
    )
    if (!yes) return
    setBusy(true)
    try {
      await api.support.remove(thread.id)
      notify(`Звернення #${thread.id} видалено`)
      await onDelete(thread.id)
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
          Клієнти згруповані зліва. Відкрийте потрібний чат, щоб побачити його окрему історію.
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
            <span className="support-thread-number">#{thread.id}</span>
          </div>
          <div className="faint support-chat-meta">
            {user.username && <span>@{user.username}</span>}
            {user.phone && <a href={`tel:${user.phone}`}>{user.phone}</a>}
            {user.tg_id && <span>Telegram ID {user.tg_id}</span>}
            {thread.created_at && <span>від {dateTime(thread.created_at)}</span>}
            {user.bot_reachable === false && <span className="support-unreachable">бот недоступний</span>}
          </div>
          {thread.status === 'closed' && (
            <div className="support-closed-meta">{closeDescription(thread)}</div>
          )}
        </div>
        <div className="support-chat-actions">
          {thread.status === 'open' ? (
            <button className="btn ghost small" onClick={closeSession} disabled={busy}>Закрити звернення</button>
          ) : (
            <button className="btn danger small" onClick={remove} disabled={busy}>Видалити</button>
          )}
        </div>
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
        {thread.status === 'closed' ? (
          <div className="support-compose-note support-compose-closed">
            <strong>Ця сесія завершена.</strong> Відповідати або перевідкривати її не можна.
            Нове питання клієнт починає окремою сесією через «🆘 Підтримка» або /ask.
          </div>
        ) : (
          <>
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
          </>
        )}
      </div>
    </section>
  )
}

export default function Support() {
  const initialThreadId = useMemo(() => {
    const value = Number(new URLSearchParams(window.location.search).get('thread') || 0)
    return Number.isInteger(value) && value > 0 ? value : null
  }, [])
  // Перехід із системного сповіщення має відкрити конкретну сесію навіть
  // якщо менеджер уже встиг її закрити, тому deep-link починає з «Усі».
  const [status, setStatus] = useState(initialThreadId ? 'all' : 'open')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('recent')
  const [threads, setThreads] = useState([])
  const [stats, setStats] = useState(EMPTY_STATS)
  const [selectedId, setSelectedId] = useState(initialThreadId)
  const [thread, setThread] = useState(null)
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadThreads = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const [data, nextStats] = await Promise.all([
        api.support.list(status),
        api.support.stats(),
      ])
      setThreads(data)
      setStats(nextStats || EMPTY_STATS)
      setError('')

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

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const map = new Map()

    for (const item of threads) {
      const user = item.user || {}
      const haystack = [user.first_name, user.username, user.phone, user.tg_id, item.id]
        .filter(Boolean).join(' ').toLowerCase()
      if (needle && !haystack.includes(needle)) continue

      const key = String(item.user_id)
      if (!map.has(key)) {
        map.set(key, { key, threads: [], unread: 0, openCount: 0, lastAt: 0, firstAt: Infinity })
      }
      const group = map.get(key)
      group.threads.push(item)
      group.unread += Number(item.unread_count || 0)
      if (item.status === 'open') group.openCount += 1
      const last = stamp(item.last_message_at || item.updated_at || item.created_at)
      const first = stamp(item.created_at)
      group.lastAt = Math.max(group.lastAt, last)
      group.firstAt = Math.min(group.firstAt, first || Infinity)
    }

    const items = [...map.values()]
    for (const group of items) {
      group.threads.sort((a, b) => stamp(b.last_message_at || b.updated_at) - stamp(a.last_message_at || a.updated_at))
    }

    items.sort((a, b) => {
      if (sort === 'unread') return (b.unread - a.unread) || (b.lastAt - a.lastAt)
      if (sort === 'name') return clientName(a.threads[0]).localeCompare(clientName(b.threads[0]), 'uk')
      if (sort === 'oldest') return (a.firstAt - b.firstAt) || (a.lastAt - b.lastAt)
      return b.lastAt - a.lastAt
    })
    return items
  }, [threads, query, sort])

  const select = (id) => {
    setSelectedId(id)
    setError('')
  }

  const changeFilter = (next) => {
    setStatus(next)
    setSelectedId(null)
    setThread(null)
    setMessages([])
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

  const deleted = async () => {
    setSelectedId(null)
    setThread(null)
    setMessages([])
    await loadThreads(true)
  }

  return (
    <>
      <div className="page-head support-page-head">
        <div>
          <h1>Підтримка</h1>
          <p>Окремі звернення з /ask зберігаються в історії та групуються по клієнтах</p>
        </div>
        <button className="btn ghost support-refresh" onClick={() => loadThreads()} disabled={loading}>
          Оновити
        </button>
      </div>

      <div className="support-stats" aria-label="Статистика підтримки">
        <button className={`support-stat ${status === 'open' ? 'active' : ''}`} onClick={() => changeFilter('open')}>
          <span>В роботі</span><strong>{stats.open}</strong>
        </button>
        <button className={`support-stat ${status === 'closed' ? 'active' : ''}`} onClick={() => changeFilter('closed')}>
          <span>Закриті</span><strong>{stats.closed}</strong>
        </button>
        <button className={`support-stat ${status === 'all' ? 'active' : ''}`} onClick={() => changeFilter('all')}>
          <span>Усього чатів</span><strong>{stats.total}</strong>
        </button>
        <div className="support-stat passive">
          <span>Клієнтів</span><strong>{stats.clients}</strong>
        </div>
        <div className={`support-stat passive ${stats.unread ? 'has-unread' : ''}`}>
          <span>Непрочитані</span><strong>{stats.unread}</strong>
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
                  onClick={() => changeFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <input
              className="input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ім’я, @username, телефон, ID або № чату"
            />
            <select className="input support-sort" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="recent">Спочатку активні</option>
              <option value="unread">Спочатку непрочитані</option>
              <option value="name">За ім’ям клієнта</option>
              <option value="oldest">Спочатку найстаріші</option>
            </select>
          </div>

          <div className="support-thread-list">
            {loading ? <Loading rows={5} /> : groups.length === 0 ? (
              <Empty title="Звернень немає">
                Нові чати створюються після /ask. Закриті залишаються в історії, доки їх не видалять вручну.
              </Empty>
            ) : groups.map((group) => (
              <ClientGroup
                key={group.key}
                group={group}
                selectedId={selectedId}
                onSelect={select}
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
          onDelete={deleted}
        />
      </div>
    </>
  )
}
