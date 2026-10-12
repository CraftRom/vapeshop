import assert from 'node:assert/strict'
import { money } from '../src/money.js'
for (const [amount, expected] of [['199.90', '199,90'], ['0.01', '0,01'], ['179.91', '179,91'], ['200', '200,00'], ['53.97', '53,97']]) {
  assert.equal(money(amount), expected)
}
assert.equal(money(null), '—')
console.log('MONEY: 6/6')
