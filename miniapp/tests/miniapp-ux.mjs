/** Regression checks for the shopping UX and Telegram lifecycle. */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { cartSignature, resumeCheckoutDraft } from '../src/checkoutSession.js'
import { trackViewport } from '../src/scroll.js'
import { isMiniAppActive, onActivityChange } from '../src/telegram.js'

let checks = 0
const check = (condition, description) => {
  assert.ok(condition, description)
  checks += 1
}
const source = name => readFileSync(new URL('../src/' + name, import.meta.url), 'utf8')
const app = source('App.jsx')
const checkout = source('screens/Checkout.jsx')
const css = source('styles.css')
const storefront = source('storefront.css')
const profile = source('screens/Profile.jsx')
const a = { lines: [{product_id: 12, qty: 2, price: '19.20'}, {product_id: 1, qty: 1, price: 10}] }
const b = { lines: [{product_id: 1, qty: 1, price: 10}, {product_id: 12, qty: 2, price: '19.20'}] }
const c = { lines: [{product_id: 1, qty: 1, price: 10}, {product_id: 12, qty: 3, price: '19.20'}] }
check(cartSignature(a) === cartSignature(b), 'cart order does not invalidate checkout draft')
check(cartSignature(a) !== cartSignature(c), 'changing quantity invalidates checkout draft')
check(cartSignature(a) !== cartSignature({...a, lines:[{...a.lines[0],price:25}, a.lines[1]]}), 'price change invalidates checkout draft')
const draft = {signature:cartSignature(a), checkoutKey:'unique-key', replayPending:true, pendingPayload:{checkout_key:'unique-key'}}
check(resumeCheckoutDraft(draft, cartSignature(b)) === draft, 'uncertain request keeps its idempotency key')
check(resumeCheckoutDraft(draft, cartSignature(c)) === null, 'mutated cart resets stale request')
check(resumeCheckoutDraft(null, cartSignature(a)) === null, 'empty draft remains empty')
check(!/(?:localStorage|sessionStorage)\.(?:setItem|getItem)/.test(source('checkoutSession.js')), 'checkout draft not persisted to browser storage')
check(app.includes('checkoutDraftRef.current = null') && app.includes('onDraftChange='), 'checkout drafts cleared after completion / auth failure')
check(checkout.includes('pendingPayload = useRef(initialDraft?.pendingPayload || null)'), 'uncertain checkout payload restored')
check(checkout.includes('initialDraft?.checkoutKey'), 'checkout idempotency key restored')
check(checkout.includes('disabled={busy} type="button" onClick={onBack}'), 'back-to-cart cannot interrupt active submission')
check(app.includes('checkoutSubmittingRef.current'), 'Telegram Back Button respects active checkout')
check(app.includes('const count = shownCart?.lines?'), 'cart badge reflects pending quantity')
check(app.includes('Зберігаємо кількість · сума уточнюється'), 'provisional cart price clearly announced')
check(css.includes('.bar[hidden] { display: none; }'), 'hidden checkout bar is not keyboard-focusable')
check(storefront.includes('.miniapp-keyboard-open .store-nav'), 'mobile keyboard does not leave the bottom navigation in the way')
check(storefront.includes('background: var(--card);') && storefront.includes('color: var(--tg-text);'), 'offline notice uses shop dark and light palettes')
check(profile.includes('aria-pressed={orderFilter === id}') && profile.includes('visibleOrders.map'), 'profile filter is accessible and actually filters orders')
check(profile.includes('(o.items || []).map'), 'malformed missing items cannot crash the entire profile')

const originalWindow = globalThis.window
const originalDocument = globalThis.document
const events = new Map()
const style = new Map()
const classes = new Set()
const appEvents = new Map()
let active = true
const appMock = {
  viewportStableHeight: 720,
  get isActive() { return active },
  onEvent(name, cb) { appEvents.set(name, cb) },
  offEvent(name, cb) { if (appEvents.get(name) === cb) appEvents.delete(name) },
}
try {
  globalThis.document = {
    activeElement: {tagName:'INPUT'},
    documentElement: {
      style: { setProperty(name, value) { style.set(name, value) } },
      classList: {
        toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name) },
        remove(name) { classes.delete(name) },
      },
    },
    addEventListener(name, fn) { events.set('doc-' + name, fn) },
    removeEventListener(name) { events.delete('doc-' + name) },
  }
  globalThis.window = {
    Telegram:{WebApp:appMock}, innerHeight:720,
    visualViewport:{height:440, addEventListener(name, fn) { events.set('visual-' + name, fn) }, removeEventListener(name) { events.delete('visual-' + name) }},
    addEventListener(name, fn) { events.set('window-' + name, fn) },
    removeEventListener(name) { events.delete('window-' + name) },
  }
  const stop = trackViewport()
  check(style.get('--viewport-height') === '440px', 'dynamic viewport sees software keyboard')
  check(style.get('--viewport-stable-height') === '720px', 'Telegram stable viewport used for layout')
  check(classes.has('miniapp-keyboard-open'), 'keyboard state detected while typing')
  window.visualViewport.height = 700
  events.get('visual-resize')()
  check(!classes.has('miniapp-keyboard-open'), 'keyboard state cleared on resize')
  check(isMiniAppActive(), 'active Telegram mini app permits realtime')
  let activated = 0
  const off = onActivityChange(() => { activated++ })
  check(appEvents.has('activated') && appEvents.has('deactivated'), 'Telegram lifecycle handlers registered')
  active = false
  appEvents.get('deactivated')()
  check(!isMiniAppActive() && activated === 1, 'minimized Telegram app suspends realtime')
  off()
  check(!appEvents.has('activated') && !appEvents.has('deactivated'), 'Telegram activity listeners cleaned up')
  stop()
  check(events.size === 0 && classes.size === 0 && appEvents.size === 0, 'viewport listeners and keyboard CSS cleaned up')
} finally {
  globalThis.window = originalWindow
  globalThis.document = originalDocument
}
console.log(`MINI APP UX: ${checks}/${checks}`)
