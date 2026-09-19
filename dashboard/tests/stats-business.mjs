import fs from 'node:fs'

const overview = fs.readFileSync(new URL('../src/pages/Overview.jsx', import.meta.url), 'utf8')
const api = fs.readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
const chart = fs.readFileSync(new URL('../src/components/RevenueChart.jsx', import.meta.url), 'utf8')

const tests = [
  ['calendar period keys', ['today', '7d', 'month', '90d', 'all'].every((x) => overview.includes(`key: '${x}'`))],
  ['received metric', overview.includes('label="Отримано"') && overview.includes('actual_received_period')],
  ['confirmed turnover metric', overview.includes('Підтверджений оборот') && overview.includes('confirmed_period')],
  ['expected money metric', overview.includes('Очікуємо отримання') && overview.includes('expected_period')],
  ['shipped amount metric', overview.includes('shipped_period') && overview.includes('shipped_orders_period')],
  ['user activity block', overview.includes('Активність користувачів') && overview.includes('buyer_share')],
  ['status breakdown follows period', api.includes("breakdown: (period = 'month')")],
  ['all stats API calls use period', ['summary', 'series', 'topProducts', 'byOperator', 'insights'].every((x) => api.includes(`${x}: (period = 'month')`))],
  ['chart separates turnover and received', chart.includes('dataKey="confirmed"') && chart.includes('dataKey="revenue"')],
  ['manager table separates received and expected', overview.includes('money(o.received)') && overview.includes('money(o.expected)')],
]

let ok = 0
for (const [name, pass] of tests) {
  console.log(`${pass ? '✓' : '✗'} ${name}`)
  if (pass) ok++
}
console.log(`STATS UI: ${ok}/${tests.length}`)
if (ok !== tests.length) process.exit(1)
