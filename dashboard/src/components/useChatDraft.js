import { useCallback, useRef, useSyncExternalStore } from 'react'
import { chatDraftEpoch, readChatDraft, writeChatDraft, subscribeChatDrafts,
  chatDraftStatus, captureChatDraft, clearSentChatDraft } from './chatDrafts'

// Keyed conversation components keep their original auth epoch even while a
// send is pending. A late acknowledgement can clear only its submitted revision.
export function useChatDraft(kind, id) {
  const key = `${kind}:${id}`
  const owner = useRef(chatDraftEpoch()).current
  const text = useSyncExternalStore(subscribeChatDrafts,
    () => owner === chatDraftEpoch() ? readChatDraft(key) : '')
  const status = useSyncExternalStore(subscribeChatDrafts, () => chatDraftStatus(key))
  const setText = useCallback(next => {
    const current = captureChatDraft(key, owner).text
    writeChatDraft(key, typeof next === 'function' ? next(current) : next, owner)
  }, [key, owner])
  const snapshot = useCallback(() => captureChatDraft(key, owner), [key, owner])
  const confirmSent = useCallback(submitted => clearSentChatDraft(key, submitted, owner), [key, owner])
  return [text, setText, { status, snapshot, confirmSent }]
}
