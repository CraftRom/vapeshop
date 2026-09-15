const mkStore = () => {
  const data = new Map()
  return {
    getItem: (k) => data.has(k) ? data.get(k) : null,
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  }
}

const webApp = { initData: '', initDataUnsafe: {}, platform: 'android' }
globalThis.window = {
  Telegram: { WebApp: webApp },
  location: {
    href: 'https://www.elfar.pp.ua/app/#tgWebAppVersion=9.6&tgWebAppPlatform=android',
    hostname: 'www.elfar.pp.ua',
    hash: '#tgWebAppVersion=9.6&tgWebAppPlatform=android',
    search: '',
    pathname: '/app/',
  },
  localStorage: mkStore(),
  sessionStorage: mkStore(),
  history: { replaceState: (_a, _b, next) => { globalThis.__replaced = next } },
}

const mod = await import(`../src/telegram.js?bridge-test=${Date.now()}`)
const signed = 'query_id=AAH123&user=%7B%22id%22%3A123%7D&auth_date=1789410000&hash=abcdef123456'
webApp.initData = signed
const target = mod.legacyHostRedirectUrl(mod.getInitData())
const url = new URL(target)

let failed = 0
const check = (ok, name) => { console.log(`  ${ok ? '✓' : '✗'} ${name}`); if (!ok) failed++ }
check(url.hostname === 'elfar.pp.ua', 'www -> canonical host')
check(url.hash.includes('elfarInitData='), 'signed payload передано через fragment bridge')
check(!url.search.includes('elfarInitData='), 'signed payload не потрапляє в HTTP query')

// Нова сторінка canonical: SDK більше не має initData, відновлюємо bridge.
webApp.initData = ''
window.location = {
  href: url.toString(), hostname: url.hostname, hash: url.hash,
  search: url.search, pathname: url.pathname,
}
const recovered = mod.getInitData()
check(recovered === signed, 'bridge відновлює initData байт-у-байт')
check(mod.initDataSource() === 'legacy bridge', 'джерело діагностики лишається legacy bridge після scrub')
check(String(globalThis.__replaced || '').includes('elfarInitData=') === false, 'bridge прибирається з address bar')

console.log(`\nМІСТОК У РОБОТІ: ${failed ? `ПРОВАЛЕНО: ${failed}` : 'усе витримано'}`)
if (failed) process.exit(1)
