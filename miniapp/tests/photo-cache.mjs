import assert from 'node:assert/strict'
import { createPhotoCache } from '../src/photoCache.js'
let now = 0
let loads = 0
const revoked = []
const cache = createPhotoCache(id => { loads++; return Promise.resolve(`blob:${id}-${loads}`) },
  url => revoked.push(url), {maxItems: 2, ttlMs: 100, clock: () => now})
const a = cache.acquire(1)
const b = cache.acquire(1)
assert.equal(await a.promise, await b.promise)
assert.equal(loads, 1, 'two cards get a single request')
a.release()
assert.equal(revoked.length, 0, 'first card cannot revoke second card URL')
b.release()
const c = cache.acquire(1)
assert.equal(await c.promise, 'blob:1-1', 'next mount reuses short-lived URL')
c.release()
now = 200
const d = cache.acquire(2)
await d.promise
assert.deepEqual(revoked, ['blob:1-1'], 'expired unused URL revoked')
const e = cache.acquire(3)
await e.promise
const f = cache.acquire(4)
await f.promise
assert.ok(cache.size() >= 2, 'mounted URLs are retained even over the size budget')
d.release();e.release();f.release()
cache.trim()
assert.ok(cache.size() <= 2, 'unused cache bounded after unmount')
const late = cache.acquire(5)
late.release()
const lateUrl = await late.promise
assert.ok(revoked.includes(lateUrl), 'late response released after unmount')
console.log('PHOTO CACHE: 7/7')
