import { readFileSync } from 'node:fs'

const app = readFileSync('src/App.jsx', 'utf8')
const page = readFileSync('src/pages/Support.jsx', 'utf8')
const api = readFileSync('src/api.js', 'utf8')
const css = readFileSync('src/styles.css', 'utf8')
const version = readFileSync('src/version.js', 'utf8')

let bad = 0
const check = (ok, label) => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}`)
}

console.log('\n--- підтримка: Telegram ↔ панель UX 1.27 ---')
check(app.includes("to: '/support'") && app.includes("path=\"/support\""), 'у панелі є окремий розділ Підтримка')
check(app.includes("badge: 'support'") && app.includes('api.stats.badges()'), 'sidebar показує непрочитані звернення')
check(api.includes("list: (status = 'open')") && api.includes('send: (id, text)'), 'API-клієнт уміє читати й відповідати')
check(page.includes('api.support.messages') && page.includes('api.support.send'), 'діалог завантажує історію й надсилає відповідь')
check(page.includes("['open', 'В роботі']") && page.includes("['closed', 'Закриті']"), 'звернення можна вести й закривати')
check(page.includes('markRead') || page.includes('mark_read') || page.includes('loadConversation(true)'), 'прочитаність оновлюється при відкритті')
check(page.includes('support-mobile-back'), 'на телефоні є повернення зі чату до списку')
check(css.includes('.support-layout') && css.includes('@media (max-width: 760px)'), 'підтримка має desktop/mobile компонування')
check(css.includes('.support-compose') && css.includes('.support-bubble'), 'чат має окремі повідомлення та поле відповіді')
check(version.includes("APP_VERSION = '1.27.1'"), 'версія панелі піднята до 1.27.1')

console.log(`\nПІДТРИМКА UX: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
