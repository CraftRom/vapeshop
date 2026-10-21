import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useVisiblePolling } from './useVisiblePolling'

function merge(...groups) {
  const byId = new Map()
  groups.forEach(group => group.forEach(message => byId.set(message.id, message)))
  return [...byId.values()].sort((a, b) => Number(a.id) - Number(b.id))
}

export function useChatMessages(kind, id) {
  const [messages, setMessages] = useState([])
  const [newMessageIds, setNewMessageIds] = useState(() => new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [hasOlder, setHasOlder] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [olderError, setOlderError] = useState('')
  const current = useRef([])
  const initialized = useRef(false)
  const epoch = useRef(0)
  const polling = useRef(null)
  const olderRequest = useRef(null)
  const tick = useRef(0)
  // Only contiguous GET results advance this cursor. A successful POST can
  // return a newer ID while earlier client replies are still in transit.
  const cursor = useRef(null)

  const commit = useCallback((fresh, prepend = false) => {
    const next = prepend ? merge(fresh, current.current) : merge(current.current, fresh)
    if (JSON.stringify(next) !== JSON.stringify(current.current)) {
      current.current = next
      setMessages(next)
    }
  }, [])

  const acknowledge = useCallback((fresh) => {
    if (kind !== 'order') return
    const unseen = fresh.filter(message => message.direction === 'in' && !message.is_read).map(message => message.id)
    if (!unseen.length) return
    setNewMessageIds((known) => {
      if (unseen.every(messageId => known.has(messageId))) return known
      const next = new Set(known)
      unseen.forEach(messageId => next.add(messageId))
      return next
    })
    if (!document.hidden) api.orders.markMessagesRead(id, unseen).catch(() => {})
  }, [kind, id])

  const refresh = useCallback(async () => {
    const owner = epoch.current
    if (polling.current === owner) return
    polling.current = owner
    try {
      {
        let after = initialized.current ? (cursor.current ?? 0) : null
        // Drain consecutive delta pages before reconciliation, so returning to
        // a busy chat cannot skip the gap between old and newest 200 messages.
        let drained = false
        for (let batch = 0; batch < 3; batch += 1) {
          const fresh = kind === 'support'
            ? await api.support.messages(id, false, after, null, 200)
            : await api.orders.messages(id, false, after, null, 200)
          if (epoch.current !== owner) return
          commit(fresh)
          acknowledge(fresh)
          if (fresh.length) cursor.current = Math.max(Number(cursor.current || 0), Number(fresh.at(-1).id))
          if (!initialized.current) setHasOlder(fresh.length >= 200)
          if (after === null || fresh.length < 200) { drained = true; break }
          const next = fresh.at(-1)?.id
          if (!next || Number(next) <= Number(after)) break
          after = next
        }
        tick.current += 1
        if (kind === 'order' && initialized.current && drained && tick.current % 6 === 0) {
          const fresh = await api.orders.messages(id, false, null, null, 200)
          if (epoch.current !== owner) return
          const known = new Set(current.current.map(message => message.id))
          const receipts = fresh.filter(message => known.has(message.id))
          commit(receipts)
          acknowledge(receipts)
        }
      }
      initialized.current = true
      setLoading(false)
      setError('')
    } catch (err) {
      if (epoch.current === owner) { setError(err.message); setLoading(false) }
    } finally {
      if (polling.current === owner) polling.current = null
    }
  }, [kind, id, commit, acknowledge])

  useEffect(() => {
    epoch.current += 1
    refresh()
    return () => { epoch.current += 1 }
  }, [refresh])
  useVisiblePolling(refresh, 5000)

  const loadOlderMessages = useCallback(async () => {
    const owner = epoch.current
    if (!hasOlder || olderRequest.current === owner) return
    const before = current.current[0]?.id
    if (!before) return
    olderRequest.current = owner
    setLoadingOlder(true)
    setOlderError('')
    try {
      const fetchMessages = kind === 'support' ? api.support.messages : api.orders.messages
      const older = await fetchMessages(id, false, null, before, 200)
      if (epoch.current !== owner) return
      // Merge with NOW, including messages received while this request waited.
      commit(older, true)
      acknowledge(older)
      setHasOlder(older.length >= 200)
      setError('')
      setOlderError('')
    } catch (err) {
      if (epoch.current === owner) {
        if (kind === 'support') setOlderError(err.message)
        else setError(err.message)
      }
    } finally {
      if (olderRequest.current === owner) {
        olderRequest.current = null
        if (epoch.current === owner) setLoadingOlder(false)
      }
    }
  }, [kind, id, hasOlder, commit, acknowledge])

  const appendSentMessage = useCallback(message => {
    if (message) commit([message])
  }, [commit])
  return { messages, newMessageIds, loading, error, refresh, appendSentMessage,
    hasOlder, loadingOlder, olderError, loadOlderMessages }
}
