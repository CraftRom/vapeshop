import assert from 'node:assert/strict'
import { backgroundSyncPlan, realtimeSyncPlan } from '../src/syncPlan.js'
const tests = [
  ['catalog active orders refresh each cycle', backgroundSyncPlan('catalog', 1).active],
  ['catalog avoids wasteful history reload', !backgroundSyncPlan('catalog', 1).history],
  ['catalog avoids profile reload in most cycles', !backgroundSyncPlan('catalog', 1).profile],
  ['catalog refreshes profile every third cycle', backgroundSyncPlan('catalog', 3).profile],
  ['saved lists also refreshed periodically', backgroundSyncPlan('catalog', 3).saved],
  ['cart refreshed every second cycle', !backgroundSyncPlan('catalog', 1).cart && backgroundSyncPlan('catalog', 2).cart],
  ['profile always refreshes full history', backgroundSyncPlan('profile', 1).history],
  ['checkout keeps contact/profile fresh', backgroundSyncPlan('checkout', 1).profile],
  ['SSE only reads full history when needed', !realtimeSyncPlan('catalog').history && realtimeSyncPlan('chat').history],
  ['SSE syncs profile while checkout', realtimeSyncPlan('checkout').profile],
]
for (const [label, ok] of tests) { assert.ok(ok, label); console.log('  ✓', label) }
console.log(`\nSYNC PLANNING: ${tests.length}/${tests.length}`)
