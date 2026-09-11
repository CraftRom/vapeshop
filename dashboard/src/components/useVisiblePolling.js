import { useEffect, useRef } from 'react'

/**
 * Фонове опитування, яке не працює даремно.
 *
 * На прихованій вкладці таймер повністю зупиняється, а не просто прокидається
 * кожні N секунд і перевіряє document.hidden. Так само не запускаємо новий
 * запит, поки попередній ще не завершився. Після повернення у вкладку,
 * фокусу вікна або відновлення мережі дані підтягуються одразу.
 */
export function useVisiblePolling(task, intervalMs, { enabled = true, immediate = false } = {}) {
  const taskRef = useRef(task)

  useEffect(() => {
    taskRef.current = task
  }, [task])

  useEffect(() => {
    if (!enabled) return undefined

    let stopped = false
    let timer = null
    let inFlight = false

    const visibleAndOnline = () => !document.hidden && navigator.onLine !== false

    const clearTimer = () => {
      if (timer !== null) {
        clearTimeout(timer)
        timer = null
      }
    }

    const schedule = (delay = intervalMs) => {
      clearTimer()
      if (!stopped && visibleAndOnline()) {
        timer = window.setTimeout(run, delay)
      }
    }

    async function run() {
      if (stopped || inFlight || !visibleAndOnline()) return
      inFlight = true
      try {
        await taskRef.current()
      } catch {
        // Polling не є критичною дією. Помилка наступної спроби не блокує UI.
      } finally {
        inFlight = false
        schedule(intervalMs)
      }
    }

    const wake = () => {
      clearTimer()
      if (visibleAndOnline()) run()
    }

    document.addEventListener('visibilitychange', wake)
    window.addEventListener('focus', wake)
    window.addEventListener('online', wake)

    if (immediate) run()
    else schedule(intervalMs)

    return () => {
      stopped = true
      clearTimer()
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('focus', wake)
      window.removeEventListener('online', wake)
    }
  }, [enabled, intervalMs, immediate])
}
