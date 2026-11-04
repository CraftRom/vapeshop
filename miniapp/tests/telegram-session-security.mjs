import assert from 'node:assert/strict'
const store = () => {
  const state = new Map()
  return {
    getItem: k => state.has(k) ? state.get(k) : null,
    setItem: (k, v) => state.set(k, String(v)),
    removeItem: k => state.delete(k),
  }
}
const localStorage = store()
const sessionStorage = store()
const webApp = { initData: '', initDataUnsafe: { user: { id: 123 } } }
globalThis.window = {
  Telegram: { WebApp: webApp }, localStorage, sessionStorage,
  location: { hostname: 'elfar.pp.ua', hash: '', search: '', pathname: '/app/', href: 'https://elfar.pp.ua/app/' },
  history: { replaceState() {} },
}
let checks = 0
const check = (value, label) => { assert.ok(value, label); checks++; console.log(`  ✓ ${label}`) }
const mod = await import(`../src/telegram.js?secure-session-${Date.now()}`)
const init = 'auth_date=1790000000&user=%7B%22id%22%3A123%7D&hash=abc123'
localStorage.setItem('tgInitData', JSON.stringify({value: 'old', at: Date.now(), userId: '123'}))
webApp.initData = init
check(mod.getInitData() === init, 'SDK is the current identity source')
check(!localStorage.getItem('tgInitData'), 'previous persistent bearer copy purged')
check(sessionStorage.getItem('tgInitData')?.includes('abc123'), 'session-only fallback available')
webApp.initData = ''
check(mod.getInitData() === init, 'WebView reload fallback works in current session')
webApp.initDataUnsafe.user.id = 999
check(mod.getInitData() === '', 'fallback rejected after detected account switch')
webApp.initDataUnsafe.user.id = 123
webApp.initData = init
mod.getInitData()
mod.clearInitDataCache()
check(!sessionStorage.getItem('tgInitData'), '401 invalidation erases session bearer')
check(mod.getInitData() === '', 'expired auth cannot be silently restored from SDK')
console.log(`\nTELEGRAM SESSION SECURITY: ${checks}/${checks}`)
