import assert from 'node:assert/strict'
import { horizontalWheel } from '../src/scroll.js'
let value = 0
const rail = { clientWidth: 100, scrollWidth: 400, get scrollLeft() { return value }, set scrollLeft(next) { value = Math.max(0, Math.min(300, next)) } }
function wheel(extra = {}) {
  let prevented = false
  horizontalWheel({ target: { closest: () => rail }, deltaY: 50, deltaX: 0, deltaMode: 0, preventDefault: () => { prevented = true }, ...extra })
  return prevented
}
assert.equal(wheel(), true); assert.equal(value, 50)
assert.equal(wheel({ deltaX: 20 }), false); assert.equal(value, 50)
assert.equal(wheel({ ctrlKey: true }), false)
assert.equal(wheel({ shiftKey: true }), false)
value = 300; assert.equal(wheel(), false)
assert.equal(wheel({ deltaY: -50 }), true); assert.equal(value, 250)
value = 0; assert.equal(wheel({ deltaMode: 1, deltaY: 2 }), true); assert.equal(value, 32)
rail.scrollWidth = 100; assert.equal(wheel(), false)
assert.equal(wheel({ target: { closest: () => null } }), false)
console.log('SCROLL: 14/14')
