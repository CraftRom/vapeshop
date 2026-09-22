import { useEffect } from 'react'

import { consumeOrderEvents, getToken } from '../api'

const MAX_RETRY_MS = 15000

/**
 * Authenticated live invalidation channel for order state. The stream carries
 * only IDs/change hints; pages still read canonical authorized API endpoints.
 */
export function RealtimeOrders() {
  useEffect(() => {
    let disposed = false
    let controller = null
    let retryTimer = null
    let retryMs = 1000

    const stop = () => {
      if (retryTimer) clearTimeout(retryTimer)
      retryTimer = null
      controller?.abort()
      controller = null
    }

    const schedule = () => {
      if (disposed || document.hidden || !navigator.onLine || !getToken()) return
      if (retryTimer) clearTimeout(retryTimer)
      retryTimer = setTimeout(connect, retryMs)
      retryMs = Math.min(MAX_RETRY_MS, Math.max(1000, retryMs * 2))
    }

    const connect = async () => {
      if (disposed || document.hidden || !navigator.onLine || !getToken()) return
      stop()
      controller = new AbortController()
      try {
        await consumeOrderEvents((payload) => {
          window.dispatchEvent(new CustomEvent('elfar:orders:changed', { detail: payload }))
        }, controller.signal)
        retryMs = 1000
      } catch (err) {
        if (err?.name === 'AbortError' || disposed) return
      }
      if (!disposed) schedule()
    }

    const onVisibility = () => {
      if (document.hidden) stop()
      else { retryMs = 1000; connect() }
    }
    const onOnline = () => { retryMs = 1000; connect() }
    const onOffline = () => stop()

    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    connect()

    return () => {
      disposed = true
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  return null
}
