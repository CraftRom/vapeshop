import fs from 'node:fs'

function check(condition, message) {
  if (!condition) throw new Error(message)
  console.log(`✓ ${message}`)
}

const page = fs.readFileSync('src/pages/OrderPage.jsx', 'utf8')
const api = fs.readFileSync('src/api.js', 'utf8')
const css = fs.readFileSync('src/styles.css', 'utf8')

check(api.includes('before_id: beforeId'), 'staff chat API supports loading older history')
check(page.includes('loadOlderMessages') && page.includes('Показати попередні повідомлення'), 'order page can load older conversation history')
check(page.includes('історія зберігається'), 'order page tells staff that conversation history persists')
check(page.includes("m.delivered === false ? 'Не доставлено'"), 'failed Telegram delivery remains truthful after reload')
check(css.includes('.receipt.failed'), 'failed delivery has its own visual state')
