// Local drafts are opened only after /auth/session confirms their account scope.
// The opaque scope is an identifier, never an authentication or CSRF token.
export const CHAT_DRAFT_PREFIX = 'elfar:chat-draft:v1:'
const CONTROL = CHAT_DRAFT_PREFIX + 'active'
const TTL = 7 * 24 * 60 * 60 * 1000
const LIMIT = 50
const MAX_TEXT = 20000
const validKey = key => /^(order|support):[1-9]\d*$/.test(key)
const validScope = scope => typeof scope === 'string' && /^[a-f0-9]{64}$/.test(scope)
const revision = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`

export function createChatDraftStore(getStorage = () => globalThis.localStorage, now = () => Date.now()) {
  const drafts = new Map(), listeners = new Set()
  let epoch = 0, scope = null, generation = null, durable = false
  const emit = () => { for (const listener of listeners) listener() }
  const storageKey = key => CHAT_DRAFT_PREFIX + scope + ':' + key
  const parse = raw => { try { return JSON.parse(raw) } catch { return null } }
  const valid = (record, limit = MAX_TEXT) => record && typeof record.text === 'string' && record.text.length <= limit
    && typeof record.revision === 'string' && record.revision.length <= 100
    && Number.isFinite(record.updatedAt) && record.updatedAt > now() - TTL && record.updatedAt <= now() + 60000
  const suspend = () => { epoch++; scope = null; generation = null; durable = false; drafts.clear(); emit() }
  const purge = storage => {
    const keys = Array.from({ length: storage.length }, (_, i) => storage.key(i))
    for (const key of keys) if (key?.startsWith(CHAT_DRAFT_PREFIX) && key !== CONTROL) storage.removeItem(key)
  }
  const owns = () => {
    if (!scope) return true // Compatibility with an API that has no draft_scope: tab memory only.
    try {
      const active = parse(getStorage().getItem(CONTROL))
      if (active?.scope !== scope || active.generation !== generation) { suspend(); return false }
      return true
    } catch { durable = false; return true }
  }
  const prune = () => {
    while (drafts.size > LIMIT) {
      const key = drafts.keys().next().value
      drafts.delete(key)
      if (scope) { try { getStorage().removeItem(storageKey(key)) } catch { durable = false } }
    }
  }
  const read = key => {
    const record = drafts.get(key)
    return valid(record, Infinity) ? record.text : ''
  }
  const refresh = key => {
    if (!owns()) return null
    // A storage failure must not replace a newer in-memory edit with old disk data.
    if (scope && drafts.get(key)?.saved !== false) {
      try {
        const record = parse(getStorage().getItem(storageKey(key)))
        if (valid(record)) drafts.set(key, { ...record, saved: true })
        else drafts.delete(key)
      } catch { durable = false }
    }
    return drafts.get(key)
  }
  const write = (key, text, owner = epoch) => {
    if (owner !== epoch || !validKey(key) || typeof text !== 'string' || !owns()) return false
    const record = { text, revision: revision(), updatedAt: now(), saved: false }
    drafts.delete(key)
    if (text) drafts.set(key, record)
    if (scope) {
      try {
        if (text.length > MAX_TEXT) throw new Error('Draft exceeds local storage limit')
        const storage = getStorage()
        if (text) storage.setItem(storageKey(key), JSON.stringify({ text, revision: record.revision, updatedAt: record.updatedAt }))
        else storage.removeItem(storageKey(key))
        record.saved = true; durable = true
      } catch {
        durable = false
        // A failed replacement must not revive its older disk version on reload.
        try { getStorage().removeItem(storageKey(key)) } catch { /* storage fully blocked */ }
      }
    }
    prune(); emit(); return true
  }
  return {
    epoch: () => epoch,
    read,
    status: key => scope && durable && drafts.get(key)?.saved !== false ? 'device' : 'tab',
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener) },
    suspend,
    activate(nextScope) {
      suspend()
      if (!validScope(nextScope)) return
      scope = nextScope
      try {
        const storage = getStorage()
        let active = parse(storage.getItem(CONTROL))
        if (active?.scope !== scope || typeof active.generation !== 'string') {
          purge(storage)
          active = { scope, generation: revision() }
          storage.setItem(CONTROL, JSON.stringify(active))
        }
        generation = active.generation
        const prefix = CHAT_DRAFT_PREFIX + scope + ':'
        const loaded = []
        for (let i = 0; i < storage.length; i++) {
          const key = storage.key(i)
          if (!key?.startsWith(prefix)) continue
          const record = parse(storage.getItem(key)), shortKey = key.slice(prefix.length)
          if (validKey(shortKey) && valid(record)) loaded.push([shortKey, { ...record, saved: true }])
        }
        // Remove expired/corrupt data on activation without touching other site preferences.
        const keep = new Set(loaded.map(([key]) => prefix + key))
        const all = Array.from({ length: storage.length }, (_, i) => storage.key(i))
        for (const key of all) if (key?.startsWith(prefix) && !keep.has(key)) storage.removeItem(key)
        loaded.sort((a, b) => a[1].updatedAt - b[1].updatedAt)
        for (const [key, record] of loaded) drafts.set(key, record)
        durable = true; prune()
      } catch { scope = null; generation = null; durable = false }
      emit()
    },
    clear() {
      suspend()
      try { const storage = getStorage(); purge(storage); storage.setItem(CONTROL, JSON.stringify({ scope: null, generation: revision() })) } catch { /* tab memory still cleared */ }
    },
    write,
    capture(key, owner = epoch) {
      if (owner !== epoch) return { text: '', revision: null }
      const record = refresh(key)
      return valid(record, Infinity) ? { text: record.text, revision: record.revision } : { text: '', revision: null }
    },
    sent(key, submitted, owner = epoch) {
      if (owner !== epoch || !submitted?.revision) return false
      const latest = refresh(key)
      if (owner !== epoch || latest?.revision !== submitted.revision) return false
      return write(key, '', owner)
    },
    storageEvent(event) {
      if (event.key === null) { suspend(); return }
      if (event.key === CONTROL) {
        const active = parse(event.newValue)
        if (scope && (active?.scope !== scope || active?.generation !== generation)) suspend()
        return
      }
      const prefix = CHAT_DRAFT_PREFIX + scope + ':'
      if (!scope || !event.key?.startsWith(prefix) || !owns()) return
      const key = event.key.slice(prefix.length)
      if (!validKey(key)) return
      // Keep a newer local edit if its storage write failed. Auth revocation
      // above still clears it; ordinary storage events must not lose the text.
      if (drafts.get(key)?.saved === false) return
      // Read current bytes, not an event's potentially delayed older payload.
      try {
        const record = parse(getStorage().getItem(event.key))
        drafts.delete(key)
        if (valid(record)) drafts.set(key, { ...record, saved: true })
        durable = true; prune(); emit()
      } catch { durable = false; emit() }
    },
  }
}

const store = createChatDraftStore()
if (typeof window !== 'undefined') window.addEventListener('storage', event => store.storageEvent(event))
export const chatDraftEpoch = store.epoch
export const readChatDraft = store.read
export const writeChatDraft = store.write
export const clearChatDrafts = store.clear
export const suspendChatDrafts = store.suspend
export const activateChatDrafts = store.activate
export const subscribeChatDrafts = store.subscribe
export const chatDraftStatus = store.status
export const captureChatDraft = store.capture
export const clearSentChatDraft = store.sent
