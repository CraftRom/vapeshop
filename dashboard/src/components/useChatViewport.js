import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

/** First reply whose bottom is below the top edge, and its offset from it. */
function anchorOf(node) {
  const top = node.getBoundingClientRect().top
  const anchor = [...node.querySelectorAll('[data-message-id]')]
    .find(item => item.getBoundingClientRect().bottom > top)
  return anchor ? { id: anchor.dataset.messageId, offset: anchor.getBoundingClientRect().top - top } : null
}

export function useChatViewport(messages, ready = true) {
  const logRef = useRef(null)
  const layout = useRef({ initialized: false, bottom: true, anchor: null, lastId: 0, scrollTop: null, scrollHeight: 0 })
  const [away, setAway] = useState(false)
  const [unseen, setUnseen] = useState(0)

  const remember = useCallback(() => {
    const node = logRef.current
    if (!node) return
    const bottom = node.scrollHeight - node.scrollTop - node.clientHeight < 60
    layout.current.bottom = bottom
    layout.current.anchor = anchorOf(node)
    layout.current.scrollTop = node.scrollTop
    layout.current.scrollHeight = node.scrollHeight
    setAway(!bottom)
    if (bottom) setUnseen(0)
  }, [])

  const restore = useCallback(() => {
    const node = logRef.current
    if (!node) return
    const state = layout.current
    // The scroll event of the user's own scroll arrives a frame later. If the
    // list re-renders first, the remembered position is stale: measure it
    // from the scroll offset we last saw and the height content had then
    // (appended replies do not move what is already on screen).
    if (state.scrollTop !== null && Math.abs(node.scrollTop - state.scrollTop) > 1) {
      state.bottom = state.scrollHeight - node.scrollTop - node.clientHeight < 60
      state.anchor = anchorOf(node)
    }
    if (state.bottom) node.scrollTop = node.scrollHeight
    else if (layout.current.anchor) {
      const { id, offset } = layout.current.anchor
      const anchor = node.querySelector(`[data-message-id="${id}"]`)
      if (anchor) node.scrollTop += anchor.getBoundingClientRect().top - node.getBoundingClientRect().top - offset
    }
    state.scrollTop = node.scrollTop
    state.scrollHeight = node.scrollHeight
  }, [])

  useLayoutEffect(() => {
    if (!ready || !logRef.current) return
    const state = layout.current
    const lastId = Number(messages.at(-1)?.id || 0)
    if (state.initialized && !state.bottom && lastId > state.lastId) {
      const added = messages.filter(message => Number(message.id) > state.lastId).length
      setUnseen(count => count + added)
    }
    restore()
    state.initialized = true
    state.lastId = lastId
    remember()
  }, [messages, ready, restore, remember])

  useEffect(() => {
    const node = logRef.current
    if (!ready || !node) return undefined
    // Image decoding and mobile keyboard/viewport resizing can change heights
    // without any message-array update. Restore the same anchor in both cases.
    const card = node.closest('.support-conversation, .order-chat-card')
    const visualViewport = window.visualViewport
    const resizeViewport = () => {
      card?.style.setProperty('--chat-visible-height', `${visualViewport?.height || window.innerHeight}px`)
      restore()
    }
    resizeViewport()
    visualViewport?.addEventListener('resize', resizeViewport)
    const observer = new ResizeObserver(restore)
    observer.observe(node)
    if (node.firstElementChild) observer.observe(node.firstElementChild)
    return () => {
      observer.disconnect()
      visualViewport?.removeEventListener('resize', resizeViewport)
    }
  }, [ready, restore])

  const jumpToLatest = useCallback(() => {
    layout.current.bottom = true
    restore()
    remember()
  }, [restore, remember])
  return { logRef, onScroll: remember, jumpToLatest, away, unseen }
}
