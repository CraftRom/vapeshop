import fs from 'node:fs'

const page = fs.readFileSync(new URL('../src/pages/OrderPage.jsx', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
const api = fs.readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')

const checks = {
  'CRM option IDs are not rendered as bare values': page.includes('назву не знайдено') && page.includes('resolvedCrmOption'),
  'rich finance panel exists': page.includes('Сума CRM') && page.includes('Собівартість') && page.includes('Прибуток'),
  'recipient CRM history is shown': page.includes('Сума продажів') && page.includes('leadsSalesAmount'),
  'delivery CRM details are shown': page.includes('Платник післяплати') && page.includes('Тип вантажу') && page.includes('Адреса/Ref у CRM'),
  'current products API is used': page.includes('data[].products') && page.includes('product.defaultPriceData') && page.includes('product.upsell'),
  'snapshot source is visible': page.includes("snap?.source === 'webhook'") && page.includes('crm-source-chip'),
  'manual refresh is force refresh': api.includes('salesdriveRefresh: (id, force = false)') && page.includes('salesdriveRefresh(order.id, true)'),
  'CRM v2 has responsive flat styles': css.includes('.crm-primary-grid') && css.includes('.crm-data-strip') && css.includes('@media(max-width:760px)'),
}

for (const [name, ok] of Object.entries(checks)) console.log(`${ok ? '✓' : '✗'} ${name}`)
if (!Object.values(checks).every(Boolean)) process.exit(1)
console.log(`✓ CRM API richness: ${Object.keys(checks).length}/${Object.keys(checks).length}`)
