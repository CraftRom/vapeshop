import { APP_VERSION } from './version'
import { getInitData, initDataSource, launchParamNames } from './telegram'

const ENDPOINT = '/api/shop/client-log'
const SESSION_KEY = 'elfarStorefrontLogSession'
const MAX_PER_SESSION = 40
let sent = 0
const once = new Set()

function sessionId() {
  try {
    let value = sessionStorage.getItem(SESSION_KEY)
    if (!value) {
      value = globalThis.crypto?.randomUUID?.() ||
        `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
      sessionStorage.setItem(SESSION_KEY, value)
    }
    return value
  } catch {
    return `${Date.now().toString(36)}-nostorage`
  }
}

function referrerOrigin() {
  if (!document.referrer) return ''
  try { return new URL(document.referrer).origin } catch { return '' }
}

function safePath(value) {
  if (!value) return ''
  try { return new URL(value, window.location.href).pathname.slice(0, 160) }
  catch { return '' }
}

function cleanDetails(details = {}) {
  const out = {}
  const forbidden = /init.?data|token|authorization|cookie|password|message.?text|(^|_)text$/i
  for (const [key, value] of Object.entries(details).slice(0, 20)) {
    if (forbidden.test(key)) continue
    if (['string', 'number', 'boolean'].includes(typeof value) || value == null) {
      out[key.slice(0, 64)] = typeof value === 'string' ? value.slice(0, 250) : value
    }
  }
  return out
}

export function diagnosticContext() {
  const init = getInitData()
  const tg = window.Telegram?.WebApp
  return {
    session_id: sessionId(),
    app_version: APP_VERSION,
    path: window.location.pathname.slice(0, 160),
    sdk: Boolean(tg),
    init_data: Boolean(init),
    init_data_length: init?.length || 0,
    init_data_source: initDataSource(),
    telegram_version: tg?.version || '',
    platform: tg?.platform || '',
    launch_params: launchParamNames(),
    origin: window.location.origin.slice(0, 160),
    referrer_origin: referrerOrigin(),
    online: navigator.onLine,
    visibility: document.visibilityState || '',
  }
}

export function clientLog(event, {
  level = 'info', message = '', status = null, durationMs = null,
  errorName = '', once: onceKey = '', ...details
} = {}) {
  if (sent >= MAX_PER_SESSION) return
  if (onceKey) {
    if (once.has(onceKey)) return
    once.add(onceKey)
  }
  sent += 1

  const payload = {
    event,
    level,
    message: String(message || '').slice(0, 500),
    ...diagnosticContext(),
    status,
    duration_ms: durationMs,
    error_name: String(errorName || '').slice(0, 80),
    details: cleanDetails(details),
  }

  try {
    fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
      credentials: 'same-origin',
    }).catch(() => {})
  } catch {
    /* Логування ніколи не повинно ламати сам магазин. */
  }
}

export function registerGlobalClientLogging() {
  clientLog('storefront.launch', { message: 'Вітрина запущена', once: 'launch' })

  window.addEventListener('error', (event) => {
    const message = event.message || 'window.error'
    const genericExternal = message === 'Script error.' && !event.filename && !event.error

    // Chromium/WebView маскує винятки сторонніх cross-origin скриптів як
    // «Script error.» без файла, рядка й самого Error. У наших логах такі
    // записи приходили переважно після згортання Telegram і не містили
    // жодної діагностики. Не видаємо їх за падіння нашого застосунку.
    if (genericExternal) {
      if (document.visibilityState !== 'hidden') {
        clientLog('storefront.runtime.external_error', {
          level: 'warning',
          message: 'Сторонній скрипт повідомив помилку без діагностики',
          once: 'generic-external-script-error',
        })
      }
      return
    }

    clientLog('storefront.runtime.error', {
      level: 'error',
      message,
      errorName: event.error?.name || '',
      file: safePath(event.filename),
      line: event.lineno || 0,
      column: event.colno || 0,
    })
  })

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    clientLog('storefront.runtime.unhandled_rejection', {
      level: 'error',
      message: reason?.message || String(reason || 'unhandled rejection'),
      errorName: reason?.name || '',
    })
  })

  window.addEventListener('offline', () => clientLog(
    'storefront.network.offline', { level: 'warning', message: 'Пристрій офлайн' },
  ))
  window.addEventListener('online', () => clientLog(
    'storefront.network.online', { message: 'Мережа відновилась' },
  ))
}
