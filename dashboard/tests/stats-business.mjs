import fs from 'node:fs'

const overview = fs.readFileSync(new URL('../src/pages/Overview.jsx', import.meta.url), 'utf8')
const api = fs.readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
const chart = fs.readFileSync(new URL('../src/components/RevenueChart.jsx', import.meta.url), 'utf8')

const tests = [
  ['calendar period keys', ['today', '7d', 'month', '90d', 'all'].every((x) => overview.includes(`key: '${x}'`))],
  ['received metric', overview.includes('label="Отримано"') && overview.includes('actual_received_period')],
  ['sale turnover metric', overview.includes('Оборот продажів') && overview.includes('sales_period') && overview.includes('sales_orders_period')],
  ['sale semantics explained', overview.includes('CRM-статусу «Продаж»') && !overview.includes('Підтверджений оборот')],
  ['expected money metric', overview.includes('Очікуємо отримання') && overview.includes('expected_period')],
  ['shipped amount metric', overview.includes('shipped_period') && overview.includes('shipped_orders_period')],
  ['user activity block', overview.includes('Активність користувачів') && overview.includes('buyer_share')],
  ['order-time activity is explicit', overview.includes('Усі оформлені замовлення за фактичним часом створення') && overview.includes('CRM-статус і час продажу на цей графік не впливають') && overview.includes('Усі оформлені замовлення за днем їх створення')],
  ['status breakdown follows period', api.includes("breakdown: (period = 'month')")],
  ['all stats API calls use period', ['summary', 'series', 'topProducts', 'byOperator', 'insights'].every((x) => api.includes(`${x}: (period = 'month')`))],
  ['chart separates sales turnover and received', chart.includes('dataKey="sales"') && chart.includes('dataKey="revenue"')],
  ['chart normalizes Decimal JSON to numbers', chart.includes('sales: Number(row?.sales ?? row?.confirmed ?? 0)') && chart.includes('revenue: Number(row?.revenue ?? 0)')],
  ['chart uses linear calendar segments', chart.includes('type="linear"') && !chart.includes('type="monotone"')],
  ['refusal metric uses commercial outcome', overview.includes('data.insights?.refusals?.orders') && overview.includes('Відмови / скасування')],
  ['manager table separates received and expected', overview.includes('money(o.received)') && overview.includes('money(o.expected)')],
]

let ok = 0
for (const [name, pass] of tests) {
  console.log(`${pass ? '✓' : '✗'} ${name}`)
  if (pass) ok++
}
console.log(`STATS UI: ${ok}/${tests.length}`)
if (ok !== tests.length) process.exit(1)
