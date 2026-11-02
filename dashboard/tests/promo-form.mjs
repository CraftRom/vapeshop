import assert from 'node:assert/strict'
import { promoDateInput, promoPayload, validatePromoForm } from '../src/promoForm.js'

const form = { code: ' sale10 ', type: 'percent', value: '10.25', min_order: '0', max_uses: '', per_user_limit: 1, expires_at: '', is_active: true }
assert.deepEqual(validatePromoForm(form), {})
assert.equal(promoPayload(form).max_uses, null)
assert.equal(promoPayload(form).value, '10.25')
assert.equal(promoPayload(form).code, 'SALE10')
assert.equal(promoPayload(form).expires_at, null)
for (const [key, value] of [['code', 'X'], ['code', 'BAD CODE'], ['value', '100.01'], ['value', '1.001'], ['min_order', '-1'], ['max_uses', '0'], ['max_uses', '1.5'], ['per_user_limit', ''], ['expires_at', '2026-02-30']]) {
  assert.ok(validatePromoForm({ ...form, [key]: value })[key], `${key}=${value} rejected`)
}
assert.deepEqual(validatePromoForm({ ...form, type: 'fixed', value: '250.50' }), {})
assert.deepEqual(validatePromoForm({ ...form, value: '100' }), {})
assert.equal(promoPayload({ ...form, expires_at: '2026-07-10' }).expires_on, '2026-07-10')
assert.equal(promoDateInput('2026-07-10T21:30:00Z'), '2026-07-11')
assert.equal(promoDateInput('2026-07-10T21:30:00'), '2026-07-11')
const original = { expires_at: '2026-07-10T21:30:00Z', category_ids: [2] }
assert.equal(promoPayload({ ...form, expires_at: '2026-07-11' }, original).expires_at, original.expires_at)
assert.equal(promoPayload({ ...form, expires_at: '2026-07-12' }, original).expires_on, '2026-07-12')
assert.deepEqual(promoPayload({ ...form, category_ids: [2] }, original).category_ids, [2])
const naive = { ...original, expires_at: '2026-07-10T21:30:00' }
assert.equal(promoPayload({ ...form, expires_at: '2026-07-11' }, naive).expires_at, '2026-07-10T21:30:00Z')
console.log('PASS promo form validation, dates, exact decimals and payloads')
