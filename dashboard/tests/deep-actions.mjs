import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

let failed = 0
const check = (ok, label) => { console.log(`${ok ? '✓' : '✗'} ${label}`); if (!ok) failed++ }

const api = readFileSync('src/api.js', 'utf8')
const order = readFileSync('src/pages/OrderPage.jsx', 'utf8')
const support = readFileSync('src/pages/Support.jsx', 'utf8')

console.log('\n--- transport панелі ---')
check(api.includes('export async function authorizedFetch'), 'є єдиний transport для авторизованих запитів')
check(api.includes('controller.abort()') && api.includes('Сервер не відповідає. Спробуйте ще раз.'), 'завислий API має timeout')
check(api.includes("if (response.status === 401)"), '401 централізовано завершує сесію')

const rawFetchOutside = []
function walk(dir) {
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, ent.name)
    if (ent.isDirectory()) walk(p)
    else if (p.endsWith('.jsx') || p.endsWith('.js')) {
      if (p === 'src/api.js') continue
      const text = readFileSync(p, 'utf8')
      if (/\bfetch\(/.test(text)) rawFetchOutside.push(p)
    }
  }
}
walk('src')
check(rawFetchOutside.length === 0, `сторінки не обходять transport напряму${rawFetchOutside.length ? `: ${rawFetchOutside.join(', ')}` : ''}`)

console.log('\n--- менеджерські дії ---')
check(order.includes('const sendingRef = useRef(false)') && order.includes('if (!body || sendingRef.current) return'), 'повідомлення замовлення захищене від double-send')
check(support.includes('const actionRef = useRef(false)') && support.includes('actionRef.current = true'), 'підтримка серіалізує send/close/delete')
const printBlock = order.slice(order.indexOf('const printLabel'), order.indexOf('const crm ='))
check(printBlock.indexOf("window.open('', '_blank')") < printBlock.indexOf('await authorizedFetch'), 'вікно PDF створюється до await і не блокується popup blocker')

console.log('\n--- кнопки ---')
let orphanButtons = []
function scanButtons(dir) {
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, ent.name)
    if (ent.isDirectory()) scanButtons(p)
    else if (p.endsWith('.jsx')) {
      const text = readFileSync(p, 'utf8')
      for (const m of text.matchAll(/<button\b([^>]*)>/gs)) {
        const a = m[1]
        if (!a.includes('onClick=') && !a.includes('type="submit"') && !a.includes("type='submit'") && !a.includes('disabled')) {
          orphanButtons.push(`${p}:${text.slice(0, m.index).split('\n').length}`)
        }
      }
    }
  }
}
scanButtons('src')
check(orphanButtons.length === 0, `немає кнопок без handler${orphanButtons.length ? `: ${orphanButtons.join(', ')}` : ''}`)

console.log(`\nDASHBOARD DEEP ACTIONS: ${failed ? `ПРОВАЛЕНО ${failed}` : 'усі перевірки пройдено'}`)
process.exit(failed ? 1 : 0)
