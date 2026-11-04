import { useEffect, useRef, useState } from 'react'

/** Browser online state is a hint, not proof that the backend is reachable. */
export function ConnectivityNotice() {
  const [online, setOnline] = useState(() => navigator.onLine !== false)
  const currentOnline = useRef(online)
  const [restored, setRestored] = useState(false)
  useEffect(() => {
    let clearNotice = null
    const update = () => {
      const next = navigator.onLine !== false
      if (!currentOnline.current && next) {
        setRestored(true)
        clearTimeout(clearNotice)
        clearNotice = setTimeout(() => setRestored(false), 2400)
      }
      if (!next) setRestored(false)
      currentOnline.current = next
      setOnline(next)
    }
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => {
      clearTimeout(clearNotice)
      window.removeEventListener('online', update)
      window.removeEventListener('offline', update)
    }
  }, [])
  if (online && !restored) return null
  return <div className={`connection-notice ${online ? 'recovered' : 'disconnected'}`}
    role="status" aria-live="polite">
    <span aria-hidden="true">{online ? '✓' : '↻'}</span>
    <span>{online ? 'Зʼєднання відновлено — дані оновлюються' : 'Немає інтернету. Дані можуть бути застарілими — не закривайте форму.'}</span>
  </div>
}
