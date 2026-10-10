import assert from 'node:assert/strict'
import { acquisition, trackVisit } from '../src/attribution.js'
let now = 1720000000000
Date.now = () => now
const storage = new Map()
globalThis.localStorage = { getItem: (k) => storage.get(k), setItem: (k, v) => storage.set(k, v) }
globalThis.window = { location: { search: '?utm_source=Google&utm_campaign=autumn&utm_medium=cpc', hostname: 'elfar.pp.ua' }, Telegram: { WebApp: { initData: 'test' } } }
globalThis.document = { referrer: '' }
const first = acquisition()
assert.equal(first.source, 'google'); assert.equal(first.campaign, 'autumn')
assert.equal(acquisition().session_id, first.session_id)
window.location.search = ''
assert.equal(acquisition().source, 'google')
now += 31 * 60000
assert.notEqual(acquisition().session_id, first.session_id)
assert.equal(acquisition().campaign, 'autumn')
now += 31 * 86400000
assert.equal(acquisition().source, 'telegram')
window.Telegram.WebApp.initDataUnsafe = { start_param: 'src_facebook__cmp_winter' }
assert.equal(acquisition().source, 'facebook'); assert.equal(acquisition().campaign, 'winter')
let calls = 0
await trackVisit({ visit: async () => { calls++ } }); await trackVisit({ visit: async () => { calls++ } })
assert.equal(calls, 1)
window.Telegram.WebApp.initDataUnsafe = { start_param: 'src_tiktok' }
await trackVisit({ visit: async () => { throw new Error('offline') } })
await trackVisit({ visit: async () => { calls++ } })
assert.equal(calls, 2)
console.log('ATTRIBUTION: 12/12')
