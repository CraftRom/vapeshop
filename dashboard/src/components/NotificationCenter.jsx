import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api'
import { dateTime, useToast } from './ui'

const SETTINGS_KEY = 'elfar:notification-settings'
const NUDGE_KEY = 'elfar:notification-nudge-dismissed'
const LEADER_KEY = 'elfar:notification-leader'
const LEADER_TTL = 16000
const POLL_MS = 10000

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

function unlockAudio() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) return
    if (!audioContext) audioContext = new AudioCtx()
    if (audioContext.state === 'suspended') audioContext.resume().catch(() => {})
  } catch { /* звук необов'язковий */ }
}

function beep(frequency, start, duration, gain = 0.045) {
  if (!audioContext || audioContext.state !== 'running') return
  const oscillator = audioContext.createOscillator()
  const volume = audioContext.createGain()
  oscillator.type = 'sine'
  oscillator.frequency.setValueAtTime(frequency, start)
  volume.gain.setValueAtTime(0.0001, start)
  volume.gain.exponentialRampToValueAtTime(gain, start + 0.015)
  volume.gain.exponentialRampToValueAtTime(0.0001, start + duration)
  oscillator.connect(volume)
  volume.connect(audioContext.destination)
  oscillator.start(start)
  oscillator.stop(start + duration + 0.02)
}

function playTone(tone) {
  unlockAudio()
  if (!audioContext || audioContext.state !== 'running') return
  const t = audioContext.currentTime + 0.02
  if (tone === 'product') {
    beep(659, t, 0.13)
    beep(880, t + 0.12, 0.18)
  } else if (tone === 'order') {
    beep(784, t, 0.12, 0.055)
    beep(1047, t + 0.11, 0.22, 0.055)
  } else if (tone === 'orderMessage') {
    beep(523, t, 0.12)
    beep(659, t + 0.13, 0.16)
  } else if (tone === 'support') {
    beep(392, t, 0.10, 0.052)
    beep(523, t + 0.10, 0.10, 0.052)
    beep(659, t + 0.20, 0.20, 0.052)
  } else {
    beep(440, t, 0.16)
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
  const initialized = useRef(false)
  const latestId = useRef(null)
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

  const announce = useCallback(async (fresh) => {
    if (!fresh.length || !isLeader()) return
    for (const item of [...fresh].sort((a, b) => a.id - b.id)) {
      if (!enabledFor(item, settings)) continue
      const tone = (KIND[item.kind] || KIND.system).tone
      if (settings.sound) playTone(tone)
      if (settings.browser && 'Notification' in window && Notification.permission === 'granted') {
        // Системний popup корисний насамперед, коли панель не перед очима.
        if (document.hidden || !document.hasFocus()) {
          await showSystemNotification(item, worker.current)
        }
      }
    }
  }, [isLeader, settings])

  const fullRefresh = useCallback(async () => {
    const data = await api.notifications.poll(undefined, 60)
    setItems(data.items || [])
    setUnread(Number(data.unread_count || 0))
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
      const fresh = data.items || []
      if (fresh.length) {
        const maxId = Math.max(latestId.current || 0, ...fresh.map((item) => Number(item.id || 0)))
        latestId.current = maxId
        setItems((current) => {
          const byId = new Map([...fresh, ...current].map((item) => [item.id, item]))
          return [...byId.values()].sort((a, b) => b.id - a.id).slice(0, 60)
        })
        await announce(fresh)
      }
      setUnread(Number(data.unread_count || 0))
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
    if (item.read) return
    try {
      const result = await api.notifications.read(item.id)
      setItems((current) => current.map((entry) => (
        entry.id === item.id ? { ...entry, read: true } : entry
      )))
      setUnread(Number(result.unread_count || 0))
    } catch { /* перехід усе одно дозволяємо */ }
  }

  const openItem = async (item) => {
    await markRead(item)
    setOpen(false)
    if (item.href) navigate(item.href)
  }

  const readAll = async () => {
    try {
      const result = await api.notifications.readAll()
      setItems((current) => current.map((item) => ({ ...item, read: true })))
      setUnread(Number(result.unread_count || 0))
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
        <div className="notification-nudge">
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
              <div className="notification-empty">Нових подій ще немає.</div>
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
