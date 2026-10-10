// First-party last non-direct attribution. No click IDs, URLs, IPs or Telegram
// credentials are persisted. A session expires after 30 min of inactivity.
const KEY = 'elfar_acquisition_v1'
const TTL = 30 * 86400000
let memory = null
let lastEntry = null
const safe = (value, max = 160) => String(value || '').trim().slice(0, max)
const sourceKey = (value) => safe(value, 80).toLowerCase().replace(/[^a-z0-9._-]+/g, '_') || 'unknown'

export function acquisition() {
  const now = Date.now()
  let state = memory
  try { state = JSON.parse(localStorage.getItem(KEY)) || state } catch {}
  const params = new URLSearchParams(window.location.search)
  const start = window.Telegram?.WebApp?.initDataUnsafe?.start_param || params.get('tgWebAppStartParam') || params.get('startapp') || ''
  const tagged = /^src_([a-z0-9._-]+?)(?:__cmp_([a-z0-9._-]+))?$/i.exec(start)
  let encoded = null
  if (start.startsWith('acq_') && start.length <= 512) {
    try { encoded = JSON.parse(atob(start.slice(4).replaceAll('-', '+').replaceAll('_', '/'))) } catch {}
  }
  let candidate = null
  if (params.get('utm_source')) {
    candidate = { source: sourceKey(params.get('utm_source')), medium: safe(params.get('utm_medium')),
      campaign: safe(params.get('utm_campaign')), content: safe(params.get('utm_content')), term: safe(params.get('utm_term')) }
  } else if (encoded?.source) {
    candidate = { source: sourceKey(encoded.source), ...Object.fromEntries(['medium', 'campaign', 'content', 'term'].map((key) => [key, safe(encoded[key])])) }
  } else if (tagged) {
    candidate = { source: sourceKey(tagged[1]), medium: 'campaign', campaign: safe(tagged[2]) }
  } else if (start.startsWith('ref_')) {
    candidate = { source: 'referral', medium: 'referral' }
  } else {
    try {
      const host = new URL(document.referrer).hostname.toLowerCase()
      if (host && host !== window.location.hostname) candidate = { source: sourceKey(host), medium: 'referral' }
    } catch {}
  }
  const entry = `${window.location.search}|${start}|${document.referrer}`
  if (entry === lastEntry) candidate = null
  lastEntry = entry
  const newSession = !state?.session_id || now - state.last_seen > 1800000
  const expired = !state?.attributed_at || now - state.attributed_at > TTL
  // A tagged entry starts a fresh session when the acquisition campaign changes.
  const changed = candidate && (candidate.source !== state?.attribution?.source || (candidate.campaign || '') !== (state?.attribution?.campaign || ''))
  if (newSession || changed) {
    state = { ...state, session_id: globalThis.crypto?.randomUUID?.() || `visit_${now}_${Math.random().toString(36).slice(2)}` }
  }
  if (candidate || expired) {
    state = { ...state, attribution: candidate || { source: window.Telegram?.WebApp?.initData ? 'telegram' : 'direct', medium: 'direct' }, attributed_at: now }
  }
  state.last_seen = now
  memory = state
  try { localStorage.setItem(KEY, JSON.stringify(state)) } catch {}
  return { ...state.attribution, session_id: state.session_id }
}

let sent = ''
export async function trackVisit(api) {
  const a = acquisition()
  if (sent === a.session_id) return
  try {
    await api.visit({ session_id: a.session_id, attribution: a })
    sent = a.session_id
  } catch { /* Telemetry is best-effort; shop interactions remain available. */ }
}
