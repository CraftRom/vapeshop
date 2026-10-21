import { getInitData } from './telegram.js'
const PREFIX = 'shop:support-send:'
const memory = new Map()
function key(threadId) {
  let id = ''
  try { id = JSON.parse(new URLSearchParams(getInitData()).get('user') || '{}').id || '' } catch { /* auth endpoint handles invalid launch data */ }
  return `${PREFIX}${id}:${threadId}`
}
export function supportRequest(threadId, text) {
  const name = key(threadId)
  let prior = memory.get(name)
  try { prior = JSON.parse(sessionStorage.getItem(name)) || prior } catch { /* memory fallback */ }
  if (prior?.text === text && prior.created > Date.now() - 86400000) return prior
  const next = {text, request_id:globalThis.crypto?.randomUUID?.() || `support_${Date.now()}_${Math.random().toString(16).slice(2)}`, created:Date.now()}
  memory.set(name,next)
  try { sessionStorage.setItem(name,JSON.stringify(next)) } catch { /* memory fallback */ }
  return next
}
export function confirmSupportRequest(threadId, requestId) {
  const name=key(threadId)
  if (memory.get(name)?.request_id === requestId) memory.delete(name)
  try { if (JSON.parse(sessionStorage.getItem(name))?.request_id === requestId) sessionStorage.removeItem(name) } catch { /* memory already cleared */ }
}
export function clearSupportRequests() {
  memory.clear()
  try { for (let i=sessionStorage.length-1;i>=0;i--) { const name=sessionStorage.key(i); if (name?.startsWith(PREFIX)) sessionStorage.removeItem(name) } } catch { /* inaccessible storage */ }
}
