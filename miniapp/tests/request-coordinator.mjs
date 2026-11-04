import assert from 'node:assert/strict'
import { createGetCoordinator } from '../src/requestCoordinator.js'

let checks = 0
const check = (predicate, description) => {
  assert.ok(predicate, description)
  console.log(`  ✓ ${description}`)
  checks++
}

const gate = createGetCoordinator()
let runs = 0
let done
const slow = () => { runs++; return new Promise(resolve => { done = resolve }) }
const first = gate.run('/profile', 'user-one', slow)
const second = gate.run('/profile', 'user-one', slow)
check(first === second, 'concurrent GETs share exactly one promise')
await Promise.resolve()
check(runs === 1, 'producer invoked once while pending')
done({ name: 'correct' })
check((await first).name === 'correct' && (await second).name === 'correct', 'both readers see one success')
await Promise.resolve()
check(gate.size() === 0, 'resolved value is not cached')
await gate.run('/profile', 'user-one', () => { runs++; return Promise.resolve({ name: 'new' }) })
check(runs === 2, 'next refresh reaches server again')
let failed = 0
const a = gate.run('/orders', 'user-one', () => Promise.reject(new Error('offline')))
try { await a } catch { failed++ }
check(failed === 1 && gate.size() === 0, 'failed GET removed from the gate')
let changed
const old = gate.run('/cart', 'user-one', () => new Promise(resolve => { changed = resolve }))
await Promise.resolve()
const other = gate.run('/cart', 'user-two', () => Promise.resolve('new-account'))
check(old !== other && await other === 'new-account', 'different Telegram signed context never reuses old promise')
changed('previous-account')
await old
gate.clear()
check(gate.size() === 0, 'session invalidation clears pending GET pointers')
console.log(`\nGET COORDINATION: ${checks}/${checks}`)
