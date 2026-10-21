import assert from 'node:assert/strict'
import { createChatDraftStore, CHAT_DRAFT_PREFIX } from '../src/components/chatDrafts.js'
let checks = 0
function check(ok, label) { assert.ok(ok, label); checks++; console.log('PASS ' + label) }
class Storage {
  data = new Map(); broken = false; quota = false
  get length() { return this.data.size }
  key(index) { return [...this.data.keys()][index] ?? null }
  getItem(key) { if (this.broken) throw Error('Denied'); return this.data.get(key) ?? null }
  setItem(key, value) { if (this.broken || this.quota) throw Error('Quota'); this.data.set(key, value) }
  removeItem(key) { if (this.broken) throw Error('Denied'); this.data.delete(key) }
}
const storage = new Storage(), A = 'a'.repeat(64), B = 'b'.repeat(64)
let time = Date.now()
const fresh = () => createChatDraftStore(() => storage, () => time)
let first = fresh()
check(first.read('order:7') === '', 'unauthenticated initial store exposes no draft')
first.activate(A)
const text = 'Текст <b> & 😀\nДругий рядок'
first.write('order:7', text); first.write('support:7', 'Підтримка')
check(first.status('order:7') === 'device', 'successful write reports device persistence')
let reload = fresh()
check(reload.read('order:7') === '', 'disk data stays hidden before confirmed authentication')
reload.activate(A)
check(reload.read('order:7') === text, 'fresh page restores full Unicode and line breaks')
check(reload.read('support:7') === 'Підтримка', 'order and support with same ID stay isolated')
check(reload.read('order:8') === '', 'another order has no inherited draft')
reload.suspend(); check(reload.read('order:7') === '', 'network session check suspends visible drafts')
reload.activate(A); check(reload.read('order:7') === text, 'network retry preserves stored data')
const submitted = reload.capture('order:7'), firstEpoch = reload.epoch()
first.write('order:7', 'Нова версія в іншій вкладці')
check(reload.sent('order:7', submitted, firstEpoch) === false, 'late acknowledgement cannot delete another tab edit')
check(reload.capture('order:7').text === 'Нова версія в іншій вкладці', 'submission reads current stored revision')
const current = reload.capture('order:7')
check(reload.sent('order:7', current), 'acknowledgement deletes exactly its submitted revision')
let reopened = fresh(); reopened.activate(A)
check(reopened.read('order:7') === '', 'sent draft does not resurrect after reopen')
reopened.write('order:9', 'Однаковий текст')
const oldSame = reopened.capture('order:9')
reopened.write('order:9', 'Однаковий текст')
check(!reopened.sent('order:9', oldSame), 'same text with newer revision is preserved')
const staleEpoch = reopened.epoch()
storage.setItem('unrelated-preference', 'keep')
reopened.clear()
check(reopened.read('support:7') === '' && !reopened.write('order:9', 'late', staleEpoch), 'logout clears drafts and rejects late writers')
check(storage.getItem('unrelated-preference') === 'keep', 'logout preserves unrelated preferences')
check(!first.write('order:7', 'Old tab after logout'), 'old tab cannot resurrect drafts even before storage event arrives')
reopened.activate(B)
check(reopened.read('support:7') === '', 'different account cannot open previous drafts')
reopened.write('order:7', 'Інший менеджер')
reopened.activate(A)
check(reopened.read('order:7') === '', 'account switch purges previous account storage')
reopened.write('order:7', 'Expired'); time += 7 * 24 * 60 * 60 * 1000 + 1
let expired = fresh(); expired.activate(A)
check(expired.read('order:7') === '', 'seven-day expiry removes old draft')
for (let i = 1; i <= 51; i++) { time++; expired.write('order:' + i, 'Draft ' + i) }
check(expired.read('order:1') === '' && expired.read('order:51') === 'Draft 51', 'fifty-entry limit evicts oldest draft')
let bounded = fresh(); bounded.activate(A)
check(bounded.read('order:1') === '' && bounded.read('order:51') === 'Draft 51', 'eviction persists on disk')
const recordKey = CHAT_DRAFT_PREFIX + A + ':order:51'
storage.setItem(recordKey, '{bad json')
let corrupt = fresh(); corrupt.activate(A)
check(corrupt.read('order:51') === '' && storage.getItem(recordKey) === null, 'corrupt record cleaned without throwing')
storage.quota = true
corrupt.write('order:8', 'RAM text')
check(corrupt.read('order:8') === 'RAM text' && corrupt.status('order:8') === 'tab', 'quota failure keeps editable RAM draft with accurate status')
check(corrupt.capture('order:8').text === 'RAM text', 'failed persistence cannot restore stale disk text during send')
storage.quota = false
corrupt.write('order:8', 'Recovered')
check(corrupt.status('order:8') === 'device', 'storage recovery persists subsequent edit')
const huge = 'x'.repeat(20001)
corrupt.write('order:8', huge)
check(corrupt.read('order:8') === huge && corrupt.capture('order:8').text === huge && corrupt.status('order:8') === 'tab', 'oversized draft remains complete in memory without silent truncation')
const unavailable = createChatDraftStore(() => { throw Error('Denied') })
unavailable.activate(A); unavailable.write('support:1', 'Private mode')
check(unavailable.read('support:1') === 'Private mode' && unavailable.status('support:1') === 'tab', 'blocked storage falls back to tab memory')
let events = 0
const unsubscribe = corrupt.subscribe(() => events++)
corrupt.storageEvent({key: recordKey, newValue: 'delayed old bytes'})
check(corrupt.read('order:51') === '', 'delayed event reads current storage rather than stale payload')
const before = events; unsubscribe(); corrupt.write('order:3', 'No subscriber')
check(events === before, 'unmount unsubscribes listeners')
corrupt.storageEvent({key:null})
check(corrupt.read('order:3') === '', 'cleared site storage revokes in-memory drafts')
const legacy = fresh(); legacy.activate(undefined); legacy.write('support:1', 'Old API')
check(legacy.read('support:1') === 'Old API' && legacy.status('support:1') === 'tab', 'old API profile safely uses tab memory')
check(!legacy.write('other:1', 'bad') && !legacy.write('order:0', 'bad'), 'invalid conversation keys are rejected')
const fullStorage = new Storage(); fullStorage.quota = true
const noCapacity = createChatDraftStore(() => fullStorage)
noCapacity.activate(A); noCapacity.write('order:1', 'Full on first visit')
check(noCapacity.read('order:1') === 'Full on first visit' && noCapacity.status('order:1') === 'tab', 'full storage on initial activation still allows RAM editing')
const replacementStorage = new Storage(), replacement = createChatDraftStore(() => replacementStorage)
replacement.activate(A); replacement.write('order:1', 'Old stored text'); replacementStorage.quota = true
replacement.write('order:1', 'New unsaved text')
const replacementReload = createChatDraftStore(() => replacementStorage); replacementReload.activate(A)
check(replacementReload.read('order:1') === '', 'failed replacement removes stale disk version rather than reviving it')
replacement.storageEvent({key: CHAT_DRAFT_PREFIX + A + ':order:1', newValue: null})
check(replacement.read('order:1') === 'New unsaved text', 'remote delete cannot erase unsaved local edit')
console.log(`CHAT DRAFT PERSISTENCE: ${checks}/${checks}`)
