import fs from 'node:fs'

const css = fs.readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
const chart = fs.readFileSync(new URL('../src/components/RevenueChart.jsx', import.meta.url), 'utf8')

const checks = [
  ['shared control height token', css.includes('--control-height: 44px')],
  ['inputs use shared height', css.includes('min-height: var(--control-height)') && css.includes('height: var(--control-height)')],
  ['grid fields do not inherit sibling top margin', css.includes('.grid > .field + .field') && css.includes('.crm-editor-grid > .field + .field')],
  ['crm controls use global control height', css.includes('.crm-editor-grid .input{min-height:var(--control-height);height:var(--control-height)}')],
  ['file inputs normalized', css.includes("input.input[type='file']") && css.includes('::file-selector-button')],
  ['chart coerces API decimals to numbers', chart.includes('confirmed: Number(row?.confirmed ?? 0)') && chart.includes('revenue: Number(row?.revenue ?? 0)')],
  ['chart uses linear daily segments', chart.includes('type="linear"') && !chart.includes('type="monotone"')],
  ['chart pins y axis at zero', chart.includes("domain={[0, 'auto']}")],
  ['chart animation cannot produce stale spline frames', chart.includes('isAnimationActive={false}')],
]

let passed = 0
for (const [name, ok] of checks) {
  console.log(`${ok ? '✓' : '✗'} ${name}`)
  if (ok) passed++
}
console.log(`FORM/CHART NORMALIZATION: ${passed}/${checks.length}`)
if (passed !== checks.length) process.exit(1)
