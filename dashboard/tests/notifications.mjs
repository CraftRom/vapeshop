import { existsSync, readFileSync } from 'node:fs'

const app = readFileSync('src/App.jsx', 'utf8')
const center = readFileSync('src/components/NotificationCenter.jsx', 'utf8')
const api = readFileSync('src/api.js', 'utf8')
const css = readFileSync('src/styles.css', 'utf8')
const html = readFileSync('index.html', 'utf8')
const nginx = readFileSync('nginx.conf', 'utf8')
const sw = readFileSync('public/notification-sw.js', 'utf8')
const manifest = readFileSync('public/manifest.webmanifest', 'utf8')
const support = readFileSync('src/pages/Support.jsx', 'utf8')
const version = readFileSync('src/version.js', 'utf8')

let bad = 0
const check = (ok, label) => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}`)
}

console.log('\n--- центр браузерних сповіщень 1.30 ---')
check(app.includes("import { NotificationCenter }") && app.includes('<NotificationCenter />'), 'центр сповіщень підключений глобально в панелі')
check(api.includes("request('/notifications/poll'") && api.includes("request('/notifications/read-all'"), 'frontend має poll/read API центру')
check(center.includes("'product.created'") && center.includes("tone: 'product'"), 'новий товар має окремий тип і звук')
check(center.includes("'order.created'") && center.includes("tone: 'order'"), 'нове замовлення має окремий тип і звук')
check(center.includes("'order.message'") && center.includes("tone: 'orderMessage'"), 'повідомлення замовлення має окремий звук')
check(center.includes("'support.message'") && center.includes("tone: 'support'"), 'повідомлення підтримки має окремий звук')
check(center.includes('Notification.requestPermission()') && center.includes('permission === \'denied\''), 'дозвіл браузера запитується лише явною дією та обробляє блокування')
check(center.includes('iPhone|iPad|iPod') && center.includes("display-mode: standalone"), 'врахована PWA-вимога Safari на iPhone/iPad')
check(center.includes('Firefox:') && center.includes('Edge:') && center.includes('Chrome:') && center.includes('Safari:'), 'є підказки для основних браузерів')
check(center.includes("navigator.serviceWorker.register('/notification-sw.js'"), 'system popup використовує service worker')
check(center.includes('LEADER_KEY') && center.includes('LEADER_TTL'), 'кілька вкладок не дублюють звук і popup')
check(center.includes('document.hidden || !document.hasFocus()'), 'native popup не дублює foreground UI')
check(center.includes('initialized.current') && center.includes('fullRefresh'), 'старі події після відкриття панелі не програються як нові')
check(html.includes('manifest.webmanifest') && existsSync('public/icon-192.png') && existsSync('public/icon-512.png'), 'PWA manifest та іконки входять у збірку')
check(manifest.includes('"display": "standalone"'), 'manifest підтримує standalone режим')
check(nginx.includes('location = /notification-sw.js') && nginx.includes('no-store'), 'service worker не застрягає в кеші після deploy')
check(sw.includes("pathname.startsWith('/app')") && sw.includes('clients.openWindow'), 'клік popup не перехоплює клієнтський Mini App')
check(css.includes('.notification-popover') && css.includes('.notification-nudge') && css.includes('@media (max-width: 760px)'), 'центр і permission prompt адаптовані під ПК та телефон')
check(support.includes("params.get('thread')") || support.includes("get('thread')"), 'сповіщення підтримки може відкрити конкретну сесію')
check(version.includes("APP_VERSION = '1.30.0'"), 'версія панелі 1.30.0')

console.log(`\nСПОВІЩЕННЯ UX: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
