import fs from 'node:fs'

const page = fs.readFileSync(new URL('../src/pages/OrderPage.jsx', import.meta.url), 'utf8')
const api = fs.readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
const version = fs.readFileSync(new URL('../src/version.js', import.meta.url), 'utf8')

const checks = [
  ['dashboard has partial SalesDrive update client', api.includes('salesdriveUpdate') && api.includes('/salesdrive`')],
  ['CRM editor exists on order page', page.includes('Редагувати дані SalesDrive') && page.includes('CrmEditPanel')],
  ['manager can be updated', page.includes('manager_id') && page.includes('Менеджер CRM')],
  ['payment date is editable', page.includes('payment_date') && page.includes('Дата оплати')],
  ['CRM comment is editable', page.includes('comment: snap.comment') && page.includes('Коментар CRM')],
  ['contact fields are editable', page.includes('counterparty_name') && page.includes('date_of_birth')],
  ['TTN has explicit carrier', page.includes("carrier: crmCarrierFromSnapshot") && page.includes('rozetka_delivery')],
  ['carrier address restriction is visible', page.includes('Місто, відділення та адресу Нової Пошти/Укрпошти')],
  ['CRM editor is responsive', css.includes('.crm-editor-grid') && css.includes('@media (max-width:700px)')],
  ['dashboard version is 1.45+', /APP_VERSION = '1\.(4[5-9]|[5-9]\d|\d{3,})\./.test(version)],
]

let ok = 0
for (const [name, pass] of checks) {
  if (!pass) {
    console.error(`✗ ${name}`)
    process.exitCode = 1
  } else {
    console.log(`✓ ${name}`)
    ok++
  }
}
console.log(`CRM order-update UX: ${ok}/${checks.length}`)
