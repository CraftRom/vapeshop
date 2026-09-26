import fs from 'node:fs'

const page = fs.readFileSync('src/pages/LandingPages.jsx', 'utf8')
const api = fs.readFileSync('src/api.js', 'utf8')
const css = fs.readFileSync('src/styles.css', 'utf8')
const version = fs.readFileSync('src/version.js', 'utf8')

const checks = [
  ['live auto refresh', page.includes('Автоперевірка без перезавантаження') && page.includes('setInterval')],
  ['draft domain is checked', page.includes('domainStatus(selected.id, form.domain || selected.domain)')],
  ['domain query supported in client', api.includes('domainStatus: (id, domain)')],
  ['DNS propagation diagnostics', page.includes('wrongAddresses') && page.includes('successfulResolvers')],
  ['status animations', css.includes('@keyframes promoPulse') && css.includes('@keyframes promoSweep')],
  ['release version', /APP_VERSION\s*=\s*['\"]\d+\.\d+\.\d+['\"]/.test(version)],
]
let failed = 0
for (const [name, ok] of checks) {
  console.log(`${ok ? '✓' : '✗'} ${name}`)
  if (!ok) failed += 1
}
if (failed) process.exit(1)
console.log(`promo domain UX: ${checks.length}/${checks.length}`)
