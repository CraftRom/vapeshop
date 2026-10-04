import assert from 'node:assert/strict'
import { categoryFor, changedSettings, SETTINGS_CATEGORIES } from '../src/settingsModel.js'
const allowed = new Set(['shop_name', 'auto_replies_enabled', 'salesdrive_api_key'])
const initial = { shop_name: 'A', auto_replies_enabled: true, salesdrive_api_connected: true }
assert.deepEqual(changedSettings(initial, initial, allowed), {})
assert.deepEqual(changedSettings({ ...initial, auto_replies_enabled: false }, initial, allowed), { auto_replies_enabled: false })
assert.deepEqual(changedSettings({ ...initial, salesdrive_api_key: '' }, initial, allowed), { salesdrive_api_key: '' })
assert.deepEqual(changedSettings({ ...initial, salesdrive_api_connected: false }, initial, allowed), {})
assert.equal(categoryFor('Автовідповіді'), 'automation')
assert.equal(categoryFor('SalesDrive'), 'integrations')
assert.equal(new Set(SETTINGS_CATEGORIES.map((item) => item.id)).size, SETTINGS_CATEGORIES.length)
console.log('SETTINGS MODEL: 7/7')
