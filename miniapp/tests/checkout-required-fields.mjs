import fs from 'node:fs'

const checkout = fs.readFileSync(new URL('../src/screens/Checkout.jsx', import.meta.url), 'utf8')
const styles = fs.readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')

const tests = [
  ['requirement component exists', checkout.includes('function Requirement({ optional = false })')],
  ['required legend shown before form', checkout.includes('checkout-required-legend')],
  ['surname marked required', checkout.includes('htmlFor="surname"><span>Прізвище</span><Requirement />')],
  ['name marked required', checkout.includes('htmlFor="name"><span>Імʼя</span><Requirement />')],
  ['phone marked required', checkout.includes('htmlFor="phone"><span>Телефон</span><Requirement />')],
  ['city marked required', checkout.includes('htmlFor="city"><span>Населений пункт</span><Requirement />')],
  ['delivery address marked required', checkout.includes("<Requirement />\n        </label>\n        <Field\n          id=\"address\"")],
  ['patronymic optional', checkout.includes('<span>По батькові</span><Requirement optional />')],
  ['promo optional', checkout.includes('htmlFor="promo"><span>Промокод</span><Requirement optional />')],
  ['comment optional', checkout.includes('<span>Коментар</span><Requirement optional />')],
  ['native required attrs exist', (checkout.match(/aria-required="true"/g) || []).length >= 5],
  ['visual styles exist', styles.includes('.field-requirement.required') && styles.includes('.field-requirement.optional')],
]
let ok = 0
for (const [name, pass] of tests) {
  console.log(`${pass ? '✓' : '✗'} ${name}`)
  if (pass) ok++
}
console.log(`CHECKOUT REQUIRED: ${ok}/${tests.length}`)
if (ok !== tests.length) process.exit(1)
