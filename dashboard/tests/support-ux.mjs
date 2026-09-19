import { readFileSync } from 'node:fs'

const app = readFileSync('src/App.jsx', 'utf8')
const page = readFileSync('src/pages/Support.jsx', 'utf8')
const api = readFileSync('src/api.js', 'utf8')
const css = readFileSync('src/styles.css', 'utf8')
const version = readFileSync('src/version.js', 'utf8')

/** Версія панелі не нижча за ту, де функцію випущено.
 *
 * Тут стояло точне «APP_VERSION = '1.32.1'», і набір падав на кожному
 * наступному випуску панелі, хоча з функцією все гаразд. Перевірка, що
 * падає від звичайного підняття версії, привчає не дивитись на провали.
 */
const atLeast = (source, minimum) => {
  const found = source.match(/APP_VERSION\s*=\s*'(\d+)\.(\d+)\.(\d+)'/)
  if (!found) return false
  const have = found.slice(1).map(Number)
  const need = minimum.split('.').map(Number)
  for (let i = 0; i < 3; i += 1) {
    if (have[i] !== need[i]) return have[i] > need[i]
  }
  return true
}

let bad = 0
const check = (ok, label) => {
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}`)
}

console.log('\n--- підтримка: багатосесійний inbox UX 1.29 ---')
check(app.includes("to: '/support'") && app.includes('path="/support"'), 'у панелі є окремий розділ Підтримка')
check(app.includes("badge: 'support'") && app.includes('api.stats.badges()'), 'sidebar показує непрочитані звернення')
check(api.includes("stats: () => request('/support/stats')") && api.includes("remove: (id)"), 'API-клієнт має статистику та ручне видалення')
check(page.includes('support-stats') && page.includes('stats.open') && page.includes('stats.closed'), 'показані лічильники відкритих і закритих чатів')
check(page.includes('support-client-group') && page.includes('group.threads.map'), 'різні чати згруповані під одним клієнтом')
check(page.includes("value=\"unread\"") || page.includes("<option value=\"unread\">"), 'є сортування за непрочитаними')
check(page.includes("<option value=\"name\">"), 'є сортування за клієнтом')
check(page.includes('api.support.setStatus') && page.includes('api.support.remove') && !page.includes('Відкрити знову'), 'чат можна закрити й видалити, але не перевідкрити')
check(page.includes('window.confirm'), 'закриття та остаточне видалення захищені підтвердженням')
check(page.includes('Ця сесія завершена') && page.includes('closeDescription'), 'закрита сесія є read-only та показує хто/коли її закрив')
check(page.includes('support-mobile-back'), 'на телефоні є повернення зі чату до списку')
check(page.includes('message.is_automatic') && page.includes('Автовідповідь') && page.includes("automatic ? 'Бот'"), 'автоматична відповідь має службовий бейдж і автора Бот')
check(css.includes('.support-bubble.automatic') && css.includes('.support-auto-badge'), 'автовідповідь візуально відрізняється лише в dashboard')
check(css.includes('.support-client-group') && css.includes('.support-session'), 'desktop inbox має групи клієнтів і окремі сесії')
check(css.includes('@media (max-width: 760px)') && css.includes('.support-chat-actions'), 'керування адаптоване для мобільного')
check(atLeast(version, '1.32.1'), 'версія панелі не нижча за 1.32.1')

console.log(`\nПІДТРИМКА UX: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
