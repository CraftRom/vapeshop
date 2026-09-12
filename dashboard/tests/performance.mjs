import { existsSync, readFileSync } from 'node:fs'

const app = readFileSync('src/App.jsx', 'utf8')
const orders = readFileSync('src/pages/Orders.jsx', 'utf8')
const polling = readFileSync('src/components/useVisiblePolling.js', 'utf8')
const css = readFileSync('src/styles.css', 'utf8')
const html = readFileSync('index.html', 'utf8')
const nginx = readFileSync('nginx.conf', 'utf8')
const api = readFileSync('src/api.js', 'utf8')
const version = readFileSync('src/version.js', 'utf8')

let bad = 0
const check = (ok, label) => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}`)
}

console.log('\n--- performance 1.27.1 ---')
check(!html.includes('fonts.googleapis.com') && !html.includes('fonts.gstatic.com'), 'Google Fonts прибрані з critical path')
check(css.includes("--body: ui-sans-serif") && css.includes("'SFMono-Regular'"), 'панель використовує системні font stacks')
check(app.includes('api.stats.badges()') && !app.includes('api.stats.summary(30)'), 'sidebar не рахує повну статистику заради двох бейджів')
check(api.includes("badges: () => request('/stats/badges')"), 'frontend використовує легкий endpoint бейджів')
check(app.includes('useVisiblePolling(pollBadges, 60000'), 'глобальний polling знижено до 60 секунд')
check(polling.includes('document.hidden') && polling.includes('inFlight'), 'polling паузиться у background і не накладає запити')
check(orders.includes('const OrderRow = memo('), 'рядки замовлень memoized')
check(orders.includes('sameUnreadCounts') && orders.includes('45000'), 'незмінені unread-дані не перерендерюють список')
check(css.includes('content-visibility: auto') && css.includes('contain-intrinsic-size'), 'довгі списки не рендерять поза viewport')
check(html.includes('href="/favicon.ico"') && existsSync('public/favicon.ico'), 'справжній favicon входить у збірку')
check(nginx.includes('location = /favicon.ico') && nginx.includes('try_files $uri =404'), 'favicon не потрапляє у SPA fallback')
check(version.includes("APP_VERSION = '1.31.4'"), 'версія панелі 1.31.4')

console.log(`\nPERFORMANCE: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
