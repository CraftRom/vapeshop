import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

// Fetching a page is not a read receipt: only visible incoming bubbles count.
export function useSupportRead(threadId, messages, viewport, ready) {
  const acknowledged = useRef(new Set())
  const retryRef = useRef(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const node = viewport.logRef.current
    if (!ready || !node) return undefined
    let stopped = false, busy = false, timer = null
    const unread = new Set(messages.filter(m => m.direction === 'in' && !m.is_read).map(m => Number(m.id)))
    const check = async () => {
      if (stopped || busy || document.hidden || navigator.onLine === false) return
      const root = node.getBoundingClientRect()
      const ids = [...node.querySelectorAll('[data-message-id]')].filter(item => {
        const r = item.getBoundingClientRect()
        return r.bottom > Math.max(root.top, 0) && r.top < Math.min(root.bottom, window.innerHeight)
      }).map(item => Number(item.dataset.messageId)).filter(id => unread.has(id) && !acknowledged.current.has(id))
      if (!ids.length) { setError('');return }
      busy = true
      try {
        for (let start = 0; start < ids.length; start += 500) {
          const batch = ids.slice(start, start + 500)
          await api.support.markMessagesRead(threadId, batch)
          batch.forEach(id => acknowledged.current.add(id))
          if (stopped) return
        }
        setError('')
        window.dispatchEvent(new CustomEvent('elfar:support:read'))
      } catch (e) {
        if (!stopped) setError(e.message || 'Не вдалося позначити прочитаними')
      } finally {
        busy = false
      }
    }
    retryRef.current = check
    const observer = new IntersectionObserver(check, { root: node })
    node.querySelectorAll('[data-message-id]').forEach(item => observer.observe(item))
    node.addEventListener('scroll', check)
    document.addEventListener('visibilitychange', check)
    window.addEventListener('focus', check)
    window.addEventListener('online', check)
    timer = window.setInterval(check, 5000)
    check()
    return () => {
      stopped = true;retryRef.current = null
      clearInterval(timer);observer.disconnect()
      node.removeEventListener('scroll', check)
      document.removeEventListener('visibilitychange', check)
      window.removeEventListener('focus', check)
      window.removeEventListener('online', check)
    }
  }, [threadId, messages, ready, viewport.logRef])
  return { error, retry: () => retryRef.current?.() }
}
