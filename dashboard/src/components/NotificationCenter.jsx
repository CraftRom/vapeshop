import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api'
import { dateTime, useToast } from './ui'

const SETTINGS_KEY = 'elfar:notification-settings'
const NUDGE_KEY = 'elfar:notification-nudge-dismissed'
const LEADER_KEY = 'elfar:notification-leader'
const LEADER_TTL = 16000
const POLL_MS = 10000
const TOAST_AUTO_DOCK_MS = 15000
const TOAST_QUEUE_LIMIT = 40
const SOUND_MASTER_GAIN = 0.98
const SOUND_COMPRESSOR_THRESHOLD = -24
const SOUND_COMPRESSOR_RATIO = 12

const KIND = {
  'product.created': { icon: '🛍️', label: 'Новий товар', tone: 'product' },
  'order.created': { icon: '🧾', label: 'Нове замовлення', tone: 'order' },
  'order.message': { icon: '💬', label: 'Чат замовлення', tone: 'orderMessage' },
  'support.message': { icon: '🆘', label: 'Підтримка', tone: 'support' },
  system: { icon: 'ℹ️', label: 'Система', tone: 'system' },
}

const DEFAULT_SETTINGS = {
  sound: true,
  browser: true,
  product: true,
  order: true,
  orderMessage: true,
  support: true,
  system: true,
}

function loadSettings() {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

function saveSettings(value) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(value))
}

function browserInfo() {
  const ua = navigator.userAgent || ''
  const ios = /iPhone|iPad|iPod/i.test(ua)
  const standalone = window.matchMedia?.('(display-mode: standalone)').matches || window.navigator.standalone === true
  const firefox = /Firefox\//i.test(ua)
  const edge = /Edg\//i.test(ua)
  const chrome = /Chrome\//i.test(ua) && !edge
  const safari = /Safari\//i.test(ua) && !chrome && !edge
  return { ios, standalone, firefox, edge, chrome, safari }
}

function permissionText(permission) {
  if (!('Notification' in window)) return 'Браузер не підтримує системні сповіщення.'
  if (permission === 'granted') return 'Системні сповіщення дозволені.'
  if (permission === 'denied') return 'Сповіщення заблоковані в налаштуваннях браузера.'
  const info = browserInfo()
  if (info.ios && !info.standalone) {
    return 'На iPhone/iPad спершу додайте панель на екран «Домівка» й відкрийте її звідти.'
  }
  return 'Дозвольте браузеру показувати сповіщення про нові події.'
}

function deniedHelp() {
  const info = browserInfo()
  if (info.firefox) return 'Firefox: значок замка → Дозволи → Надсилати сповіщення.'
  if (info.safari && !info.ios) return 'Safari: Налаштування → Вебсайти → Сповіщення → elfar.pp.ua → Дозволити.'
  if (info.edge) return 'Edge: значок замка → Дозволи для цього сайту → Сповіщення → Дозволити.'
  if (info.chrome) return 'Chrome: значок налаштувань сайту біля адреси → Сповіщення → Дозволити.'
  return 'Відкрийте налаштування дозволів цього сайту в браузері та дозвольте сповіщення.'
}

let audioContext = null
let audioMaster = null
let audioCompressor = null

function ensureAudioGraph() {
  const AudioCtx = window.AudioContext || window.webkitAudioContext
  if (!AudioCtx) return false
  if (!audioContext) audioContext = new AudioCtx()

  if (!audioMaster || !audioCompressor) {
    audioMaster = audioContext.createGain()
    audioCompressor = audioContext.createDynamicsCompressor()

    // Максимально щільний, але контрольований сигнал. Просто множити gain вище 1
    // майже не додає гучності — браузер/ОС обрізає пік. Компресор + гармоніки
    // дають значно вищу сприйману гучність без випадкового жорсткого кліпінгу.
    audioMaster.gain.value = SOUND_MASTER_GAIN
    audioCompressor.threshold.value = SOUND_COMPRESSOR_THRESHOLD
    audioCompressor.knee.value = 10
    audioCompressor.ratio.value = SOUND_COMPRESSOR_RATIO
    audioCompressor.attack.value = 0.002
    audioCompressor.release.value = 0.16

    audioMaster.connect(audioCompressor)
    audioCompressor.connect(audioContext.destination)
  }
  return true
}

function unlockAudio() {
  try {
    if (!ensureAudioGraph()) return
    if (audioContext.state === 'suspended') audioContext.resume().catch(() => {})
  } catch { /* звук необов'язковий */ }
}

function oscillatorVoice(frequency, start, duration, gain, type = 'square') {
  if (!audioContext || audioContext.state !== 'running' || !audioMaster) return
  const oscillator = audioContext.createOscillator()
  const envelope = audioContext.createGain()

  oscillator.type = type
  oscillator.frequency.setValueAtTime(frequency, start)

  // Швидка атака + короткий sustain роблять сигнал помітним навіть на малих
  // динаміках телефона/ноутбука. Наприкінці — м'який спад без клацання.
  envelope.gain.setValueAtTime(0.0001, start)
  envelope.gain.exponentialRampToValueAtTime(Math.max(0.001, gain), start + 0.008)
  envelope.gain.setValueAtTime(Math.max(0.001, gain * 0.9), start + Math.max(0.012, duration - 0.055))
  envelope.gain.exponentialRampToValueAtTime(0.0001, start + duration)

  oscillator.connect(envelope)
  envelope.connect(audioMaster)
  oscillator.start(start)
  oscillator.stop(start + duration + 0.025)
}

function beep(frequency, start, duration, gain = 0.62, type = 'square') {
  if (!audioContext || audioContext.state !== 'running') return

  // Основний голос + дві гармоніки. Це значно гучніше на слух за один тихий
  // sine-осцилятор, особливо на вбудованих динаміках і смартфонах.
  oscillatorVoice(frequency, start, duration, gain, type)
  oscillatorVoice(frequency * 2, start, duration, gain * 0.20, 'sine')
  oscillatorVoice(frequency * 0.5, start, duration, gain * 0.16, 'triangle')
}

function playTone(tone) {
  unlockAudio()
  if (!audioContext || audioContext.state !== 'running') return
  const t = audioContext.currentTime + 0.025

  if (tone === 'product') {
    beep(720, t, 0.18, 0.62)
    beep(980, t + 0.14, 0.26, 0.72)
  } else if (tone === 'order') {
    beep(820, t, 0.18, 0.72)
    beep(1100, t + 0.14, 0.30, 0.82)
  } else if (tone === 'orderMessage') {
    beep(620, t, 0.16, 0.62, 'triangle')
    beep(840, t + 0.13, 0.24, 0.74)
  } else if (tone === 'support') {
    // Підтримка має бути найпомітнішою: три щільні імпульси + фінальний акцент.
    beep(540, t, 0.15, 0.76)
    beep(760, t + 0.12, 0.16, 0.82)
    beep(1020, t + 0.24, 0.24, 0.88)
    beep(1020, t + 0.52, 0.20, 0.78)
  } else {
    beep(700, t, 0.24, 0.68)
  }
}

function makeLeaderId() {
  return `${Date.now()}:${Math.random().toString(36).slice(2)}`
}

function useNotificationLeader() {
  const id = useRef(makeLeaderId())
  const leader = useRef(false)

  useEffect(() => {
    const claim = () => {
      const now = Date.now()
      let current = null
      try { current = JSON.parse(localStorage.getItem(LEADER_KEY) || 'null') } catch { current = null }
      if (!current || current.expires < now || current.id === id.current) {
        localStorage.setItem(LEADER_KEY, JSON.stringify({ id: id.current, expires: now + LEADER_TTL }))
        leader.current = true
      } else {
        leader.current = false
      }
    }
    claim()
    const timer = setInterval(claim, 5000)
    const onStorage = (event) => event.key === LEADER_KEY && claim()
    window.addEventListener('storage', onStorage)
    return () => {
      clearInterval(timer)
      window.removeEventListener('storage', onStorage)
      try {
        const current = JSON.parse(localStorage.getItem(LEADER_KEY) || 'null')
        if (current?.id === id.current) localStorage.removeItem(LEADER_KEY)
      } catch { /* ignore */ }
    }
  }, [])

  return () => leader.current
}

async function registerWorker() {
  if (!('serviceWorker' in navigator)) return null
  try {
    return await navigator.serviceWorker.register('/notification-sw.js', { scope: '/' })
  } catch {
    return null
  }
}

async function showSystemNotification(item, registration) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return
  const meta = KIND[item.kind] || KIND.system
  const options = {
    body: [item.actor, item.body].filter(Boolean).join(' · ').slice(0, 240),
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    tag: `elfar-notification-${item.id}`,
    renotify: true,
    data: { href: item.href || '/' },
  }
  if (registration?.showNotification) {
    try {
      await registration.showNotification(`${meta.icon} ${item.title}`, options)
      return
    } catch { /* Safari/старий браузер — пробуємо звичайний Notification */ }
  }
  try {
    const notice = new Notification(`${meta.icon} ${item.title}`, options)
    notice.onclick = () => {
      window.focus()
      if (item.href) window.location.href = item.href
      notice.close()
    }
  } catch { /* системні повідомлення — додаткові */ }
}

function enabledFor(item, settings) {
  const tone = (KIND[item.kind] || KIND.system).tone
  return settings[tone] !== false
}

function ToastCard({ item, compact = false, stackIndex = 0, onOpen }) {
  const meta = KIND[item.kind] || KIND.system
  const style = compact
    ? {
        '--toast-stack-offset': `${stackIndex * 10}px`,
        '--toast-stack-scale': String(1 - stackIndex * 0.026),
        zIndex: 20 - stackIndex,
        pointerEvents: stackIndex === 0 ? 'auto' : 'none',
      }
    : undefined

  return (
    <button
      type="button"
      className={`notification-toast-card tone-${meta.tone} ${compact ? 'is-stacked' : ''}`}
      style={style}
      onClick={() => onOpen(item)}
    >
      <span className="notification-toast-icon" aria-hidden="true">{meta.icon}</span>
      <span className="notification-toast-copy">
        <span className="notification-toast-title">
          <strong>{item.title}</strong>
          {!item.read && <i className="notification-dot" />}
        </span>
        {item.body && <span className="notification-toast-body">{item.body}</span>}
        <small>{[item.actor, item.created_at ? dateTime(item.created_at) : ''].filter(Boolean).join(' · ')}</small>
      </span>
      <span className="notification-toast-arrow" aria-hidden="true">›</span>
    </button>
  )
}

function NotificationToastStack({ items, docked, expanded, onHoverExpand, onPinExpand, onCollapse, onDock, onOpen }) {
  if (!items.length) return null

  const compactItems = items.slice(0, 3)
  const extra = Math.max(0, items.length - compactItems.length)
  const latest = items[0]
  const latestMeta = KIND[latest.kind] || KIND.system

  if (docked && !expanded) {
    return (
      <button
        type="button"
        className={`notification-toast-dock tone-${latestMeta.tone}`}
        onClick={onPinExpand}
        aria-label={`Відкрити нові сповіщення: ${items.length}`}
      >
        <span className="notification-toast-dock-pulse" aria-hidden="true" />
        <span className="notification-toast-dock-icon" aria-hidden="true">{latestMeta.icon}</span>
        <span className="notification-toast-dock-copy">
          <strong>{items.length}</strong>
          <small>{items.length === 1 ? 'нове' : 'нових'}</small>
        </span>
      </button>
    )
  }

  return (
    <section
      className={`notification-toast-stage ${expanded ? 'is-expanded' : 'is-compact'}`}
      aria-label="Нові сповіщення"
      onMouseEnter={onHoverExpand}
      onMouseLeave={onCollapse}
      onFocusCapture={onPinExpand}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) onCollapse()
      }}
    >
      {expanded ? (
        <div className="notification-toast-panel">
          <div className="notification-toast-panel-head">
            <span>
              <strong>Нові сповіщення</strong>
              <small>{items.length} у цьому стеку</small>
            </span>
            <button type="button" className="notification-toast-minimize" onClick={onDock} aria-label="Згорнути сповіщення">−</button>
          </div>
          <div className="notification-toast-scroll">
            {items.map((item) => <ToastCard key={item.id} item={item} onOpen={onOpen} />)}
          </div>
        </div>
      ) : (
        <div className="notification-toast-compact-stack">
          {[...compactItems].reverse().map((item, reverseIndex) => {
            const stackIndex = compactItems.length - 1 - reverseIndex
            return <ToastCard key={item.id} item={item} compact stackIndex={stackIndex} onOpen={onOpen} />
          })}
          {extra > 0 && (
            <button type="button" className="notification-toast-overflow" onClick={onPinExpand}>
              +{extra} ще
            </button>
          )}
          {items.length > 1 && (
            <button type="button" className="notification-toast-expand" onClick={onPinExpand}>
              {items.length} сповіщень
            </button>
          )}
        </div>
      )}
    </section>
  )
}

export function NotificationCenter() {
  const navigate = useNavigate()
  const notify = useToast()
  const isLeader = useNotificationLeader()
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState([])
  const [unread, setUnread] = useState(0)
  const [settings, setSettings] = useState(loadSettings)
  const [permission, setPermission] = useState(
    'Notification' in window ? Notification.permission : 'unsupported',
  )
  const [showSettings, setShowSettings] = useState(false)
  const [showNudge, setShowNudge] = useState(() => (
    'Notification' in window && Notification.permission === 'default' && localStorage.getItem(NUDGE_KEY) !== '1'
  ))
  const [toastItems, setToastItems] = useState([])
  const [toastDocked, setToastDocked] = useState(false)
  const [toastExpanded, setToastExpanded] = useState(false)
  const [toastPinned, setToastPinned] = useState(false)
  const toastExpandedRef = useRef(false)
  const toastTimer = useRef(null)
  const initialized = useRef(false)
  const latestId = useRef(null)
  const unreadRef = useRef(0)
  const worker = useRef(null)
  const polling = useRef(false)
  const centerRef = useRef(null)

  useEffect(() => {
    const unlock = () => unlockAudio()
    window.addEventListener('pointerdown', unlock, { once: true, passive: true })
    window.addEventListener('keydown', unlock, { once: true })
    registerWorker().then((reg) => { worker.current = reg })
  }, [])

  useEffect(() => {
    const syncPermission = () => {
      if (!('Notification' in window)) return
      setPermission(Notification.permission)
      if (Notification.permission !== 'default') setShowNudge(false)
    }
    window.addEventListener('focus', syncPermission)
    return () => window.removeEventListener('focus', syncPermission)
  }, [])

  const updateSettings = (patch) => {
    setSettings((current) => {
      const next = { ...current, ...patch }
      saveSettings(next)
      return next
    })
  }

  useEffect(() => {
    toastExpandedRef.current = toastExpanded
  }, [toastExpanded])

  const clearToastTimer = useCallback(() => {
    if (toastTimer.current) {
      clearTimeout(toastTimer.current)
      toastTimer.current = null
    }
  }, [])

  const armToastDock = useCallback(() => {
    clearToastTimer()
    toastTimer.current = setTimeout(() => {
      setToastExpanded(false)
      setToastPinned(false)
      setToastDocked(true)
      toastTimer.current = null
    }, TOAST_AUTO_DOCK_MS)
  }, [clearToastTimer])

  const showToastBatch = useCallback((fresh) => {
    const visible = fresh.filter((item) => enabledFor(item, settings))
    if (!visible.length) return visible

    setToastItems((current) => {
      const byId = new Map([...visible, ...current].map((item) => [item.id, item]))
      return [...byId.values()]
        .sort((a, b) => Number(b.id || 0) - Number(a.id || 0))
        .slice(0, TOAST_QUEUE_LIMIT)
    })
    setToastDocked(false)
    if (!toastExpandedRef.current) {
      setToastExpanded(false)
      setToastPinned(false)
      armToastDock()
    }
    return visible
  }, [armToastDock, settings])

  const hoverExpandToasts = useCallback(() => {
    clearToastTimer()
    setToastDocked(false)
    setToastExpanded(true)
  }, [clearToastTimer])

  const pinExpandToasts = useCallback(() => {
    clearToastTimer()
    setToastDocked(false)
    setToastExpanded(true)
    setToastPinned(true)
  }, [clearToastTimer])

  const collapseToasts = useCallback(() => {
    if (toastPinned) return
    setToastExpanded(false)
    armToastDock()
  }, [armToastDock, toastPinned])

  const dockToasts = useCallback(() => {
    clearToastTimer()
    setToastExpanded(false)
    setToastPinned(false)
    setToastDocked(true)
  }, [clearToastTimer])

  useEffect(() => () => clearToastTimer(), [clearToastTimer])

  const announce = useCallback(async (fresh) => {
    if (!fresh.length || !isLeader()) return
    const visible = showToastBatch(fresh)
    for (const item of [...visible].sort((a, b) => a.id - b.id)) {
      const tone = (KIND[item.kind] || KIND.system).tone
      if (settings.sound) playTone(tone)
      if (settings.browser && 'Notification' in window && Notification.permission === 'granted') {
        // Системний popup корисний насамперед, коли панель не перед очима.
        if (document.hidden || !document.hasFocus()) {
          await showSystemNotification(item, worker.current)
        }
      }
    }
  }, [isLeader, settings, showToastBatch])

  const fullRefresh = useCallback(async () => {
    const data = await api.notifications.poll(undefined, 60)
    const unreadItems = (data.items || []).filter((item) => !item.read)
    const nextUnread = Number(data.unread_count || 0)
    setItems(unreadItems)
    setUnread(nextUnread)
    unreadRef.current = nextUnread
    latestId.current = Number(data.latest_id || 0)
    initialized.current = true
  }, [])

  const poll = useCallback(async () => {
    if (polling.current) return
    polling.current = true
    try {
      if (!initialized.current) {
        await fullRefresh()
        return
      }
      const data = await api.notifications.poll(latestId.current || 0, 60)
      const nextUnread = Number(data.unread_count || 0)

      // Інша вкладка могла вже прочитати/прибрати подію або джерело
      // (замовлення/support thread/товар) могло бути видалене. У такому
      // разі incremental poll не поверне старий id, тому синхронізуємо
      // повний список, щойно серверний unread зменшився.
      if (nextUnread < unreadRef.current) {
        await fullRefresh()
        return
      }

      const fresh = (data.items || []).filter((item) => !item.read)
      if (fresh.length) {
        const maxId = Math.max(latestId.current || 0, ...fresh.map((item) => Number(item.id || 0)))
        latestId.current = maxId
        setItems((current) => {
          const byId = new Map([...fresh, ...current].map((item) => [item.id, item]))
          return [...byId.values()]
            .filter((item) => !item.read)
            .sort((a, b) => b.id - a.id)
            .slice(0, 60)
        })
        await announce(fresh)
      }
      setUnread(nextUnread)
      unreadRef.current = nextUnread
    } catch {
      // Глобальний poll не показує toast кожні 10 секунд при мережевій помилці.
      // Сторінкові запити дадуть достатньо явний сигнал, а центр спробує ще раз.
    } finally {
      polling.current = false
    }
  }, [announce, fullRefresh])

  useEffect(() => {
    poll()
    const timer = setInterval(poll, POLL_MS)
    const onVisibility = () => poll()
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('online', onVisibility)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('online', onVisibility)
    }
  }, [poll])

  useEffect(() => {
    if (!open) return
    // При відкритті беремо повний список: інша вкладка могла прочитати події.
    fullRefresh().catch(() => {})
  }, [open, fullRefresh])

  useEffect(() => {
    if (!open) return undefined
    const outside = (event) => {
      if (centerRef.current && !centerRef.current.contains(event.target)) setOpen(false)
    }
    const key = (event) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', key)
    }
  }, [open])

  const markRead = async (item) => {
    if (item.read) return true
    try {
      const result = await api.notifications.read(item.id)
      // Центр — робоча черга, а не архів. Після відкриття подія одразу
      // зникає зі списку, але read-мітка лишається на сервері.
      setItems((current) => current.filter((entry) => entry.id !== item.id))
      setToastItems((current) => current.filter((entry) => entry.id !== item.id))
      const nextUnread = Number(result.unread_count || 0)
      setUnread(nextUnread)
      unreadRef.current = nextUnread
      return true
    } catch (err) {
      // Якщо джерело вже видалили, cleanup міг прибрати й саму подію між
      // рендерами. Не лишаємо «мертвий» рядок до наступного перезавантаження.
      if (err?.status === 404) {
        setItems((current) => current.filter((entry) => entry.id !== item.id))
        setToastItems((current) => current.filter((entry) => entry.id !== item.id))
        fullRefresh().catch(() => {})
        return false
      }
      // За мережевої помилки перехід усе одно дозволяємо: ціль може бути жива.
      return true
    }
  }

  const openItem = async (item) => {
    const exists = await markRead(item)
    setOpen(false)
    if (!exists) {
      notify('Це сповіщення вже неактуальне — пов’язаний запис видалено.')
      return
    }
    if (item.href) navigate(item.href)
  }

  const openToastItem = async (item) => {
    setToastPinned(false)
    setToastExpanded(false)
    setToastDocked(false)
    armToastDock()
    await openItem(item)
  }

  const readAll = async () => {
    try {
      const result = await api.notifications.readAll()
      setItems([])
      const nextUnread = Number(result.unread_count || 0)
      setUnread(nextUnread)
      unreadRef.current = nextUnread
      clearToastTimer()
      setToastItems([])
      setToastDocked(false)
      setToastExpanded(false)
      setToastPinned(false)
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  const askPermission = async () => {
    unlockAudio()
    if (!('Notification' in window)) {
      notify('Цей браузер не підтримує системні сповіщення.', 'bad')
      return
    }
    const info = browserInfo()
    if (info.ios && !info.standalone) {
      notify('На iPhone/iPad додайте панель на екран «Домівка» й відкрийте її звідти.', 'bad')
      return
    }
    try {
      const value = await Notification.requestPermission()
      setPermission(value)
      if (value !== 'default') setShowNudge(false)
      if (value === 'granted') {
        worker.current = worker.current || await registerWorker()
        updateSettings({ browser: true })
        notify('Системні сповіщення увімкнено')
        await showSystemNotification({
          id: `test-${Date.now()}`,
          kind: 'system',
          title: 'Сповіщення працюють',
          body: 'Нові події магазину з’являтимуться тут.',
          href: '/',
        }, worker.current)
      } else if (value === 'denied') {
        notify('Браузер заблокував сповіщення. Дозвіл змінюється в налаштуваннях сайту.', 'bad')
      }
    } catch {
      notify('Не вдалося запросити дозвіл браузера.', 'bad')
    }
  }

  const testSound = () => {
    unlockAudio()
    playTone('support')
  }

  const metaItems = useMemo(() => items.map((item) => ({
    ...item,
    meta: KIND[item.kind] || KIND.system,
  })), [items])

  return (
    <div className="notification-center" ref={centerRef}>
      <button
        className={`notification-bell ${unread ? 'has-unread' : ''}`}
        type="button"
        aria-label={`Сповіщення${unread ? `: ${unread} непрочитаних` : ''}`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">🔔</span>
        {unread > 0 && <span className="notification-count">{unread > 99 ? '99+' : unread}</span>}
      </button>

      {showNudge && !open && (
        <div className={`notification-nudge ${toastItems.length ? 'has-live-toasts' : ''}`}>
          <button
            type="button"
            className="notification-nudge-main"
            onClick={askPermission}
          >
            <span>🔔</span>
            <span>
              <strong>Увімкнути сповіщення</strong>
              <small>Нові замовлення, чати й підтримка</small>
            </span>
          </button>
          <button
            type="button"
            className="notification-nudge-close"
            aria-label="Не показувати підказку"
            onClick={() => { localStorage.setItem(NUDGE_KEY, '1'); setShowNudge(false) }}
          >×</button>
        </div>
      )}

      {!open && (
        <NotificationToastStack
          items={toastItems}
          docked={toastDocked}
          expanded={toastExpanded}
          onHoverExpand={hoverExpandToasts}
          onPinExpand={pinExpandToasts}
          onCollapse={collapseToasts}
          onDock={dockToasts}
          onOpen={openToastItem}
        />
      )}

      {open && (
        <div className="notification-popover" role="dialog" aria-label="Центр сповіщень">
          <div className="notification-head">
            <div>
              <strong>Сповіщення</strong>
              <span className="faint">{unread ? `${unread} непрочитаних` : 'Усе переглянуто'}</span>
            </div>
            <div className="notification-head-actions">
              <button className="btn ghost small" onClick={() => setShowSettings((v) => !v)} aria-label="Налаштування сповіщень">⚙</button>
              {unread > 0 && <button className="btn ghost small" onClick={readAll}>Прочитати всі</button>}
            </div>
          </div>

          {showSettings && (
            <div className="notification-settings">
              <div className="notification-permission-row">
                <div>
                  <strong>Системні сповіщення браузера</strong>
                  <span className="faint">{permissionText(permission)}</span>
                  {permission === 'denied' && <span className="faint notification-help">{deniedHelp()}</span>}
                </div>
                {permission === 'default' && (
                  <button className="btn small" onClick={askPermission}>Дозволити</button>
                )}
              </div>

              <label className="notification-toggle">
                <input type="checkbox" checked={settings.sound} onChange={(e) => updateSettings({ sound: e.target.checked })} />
                <span>Звуки</span>
                <button type="button" className="btn ghost small" onClick={testSound}>Тест</button>
              </label>
              <label className="notification-toggle">
                <input type="checkbox" checked={settings.browser} onChange={(e) => updateSettings({ browser: e.target.checked })} />
                <span>Системні popup-повідомлення</span>
              </label>
              <div className="notification-kind-grid">
                {[
                  ['product', '🛍️ Новий товар'],
                  ['order', '🧾 Нове замовлення'],
                  ['orderMessage', '💬 Повідомлення в замовленні'],
                  ['support', '🆘 Підтримка'],
                  ['system', 'ℹ️ Система'],
                ].map(([key, label]) => (
                  <label key={key} className="notification-kind-toggle">
                    <input type="checkbox" checked={settings[key] !== false} onChange={(e) => updateSettings({ [key]: e.target.checked })} />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {permission === 'default' && !showSettings && (
            <button className="notification-permission-banner" onClick={askPermission}>
              <span>🔔</span>
              <span><strong>Увімкнути повідомлення браузера</strong><small>Щоб не пропускати нові чати й замовлення</small></span>
              <span>→</span>
            </button>
          )}

          <div className="notification-list">
            {metaItems.length === 0 ? (
              <div className="notification-empty">Непрочитаних сповіщень немає.</div>
            ) : metaItems.map((item) => (
              <button
                type="button"
                className={`notification-item ${item.read ? '' : 'unread'}`}
                key={item.id}
                onClick={() => openItem(item)}
              >
                <span className="notification-icon" aria-hidden="true">{item.meta.icon}</span>
                <span className="notification-copy">
                  <span className="notification-title-row">
                    <strong>{item.title}</strong>
                    {!item.read && <i className="notification-dot" />}
                  </span>
                  {item.body && <span>{item.body}</span>}
                  <small>{[item.actor, item.created_at ? dateTime(item.created_at) : ''].filter(Boolean).join(' · ')}</small>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
