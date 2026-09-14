import fs from 'node:fs'

const tg = fs.readFileSync('src/telegram.js', 'utf8')
const main = fs.readFileSync('src/main.jsx', 'utf8')
const version = fs.readFileSync('src/version.js', 'utf8')
const nginx = fs.readFileSync('nginx.conf', 'utf8')
let failed = 0
function check(ok, name) { console.log(`${ok ? 'OK' : 'FAIL'} ${name}`); if (!ok) failed++ }

check(version.includes("2.8.3"), 'Mini App 2.8.3')
check(main.includes('await waitForInitData(4000)'), 'на legacy www Telegram отримує до 4 с на initData')
check(main.includes('legacyHostRedirectUrl(initData)'), 'отриманий підпис передається в canonical redirect')
check(tg.includes("const BRIDGE_PARAM = 'elfarInitData'"), 'bridge має окремий fragment-параметр')
check(tg.includes('encodeURIComponent(initData)'), 'підпис кодується як одне fragment-значення')
check(tg.includes('decodeURIComponent(match[1])'), 'canonical host відновлює bridge')
check(tg.includes('stripBridgeFromUrl()'), 'після кешування bridge прибирається з address bar')
check(tg.includes('CACHE_TTL_MS = 15 * 60 * 1000'), 'persistent fallback обмежено 15 хвилинами')
check(tg.includes('currentUserId') && tg.includes('sameUser'), 'кеш не використовується для іншого Telegram user коли id доступний')
check(main.includes('authBridged: Boolean(initData)'), 'результат recovery видно у storefront log')
check((nginx.match(/no-store, no-cache, must-revalidate/g) || []).length >= 2, 'HTML /app і /app/ не кешуються Telegram WebView')

if (failed) process.exit(1)
