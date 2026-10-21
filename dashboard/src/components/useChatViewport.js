import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

export function useChatViewport(messages, ready = true) {
  const logRef = useRef(null)
  const layout = useRef({ initialized: false, bottom: true, anchor: null, lastId: 0 })
  const [away, setAway] = useState(false)
  const [unseen, setUnseen] = useState(0)

  const remember = useCallback(() => {
    const node = logRef.current
    if (!node) return
    const bottom = node.scrollHeight - node.scrollTop - node.clientHeight < 60
    layout.current.bottom = bottom
    const top = node.getBoundingClientRect().top
    const anchor = [...node.querySelectorAll('[data-message-id]')]
      .find(item => item.getBoundingClientRect().bottom > top)
    layout.current.anchor = anchor ? { id: anchor.dataset.messageId, offset: anchor.getBoundingClientRect().top - top } : null
    setAway(!bottom)
    if (bottom) setUnseen(0)
  }, [])

  const restore = useCallback(() => {
    const node = logRef.current
    if (!node) return
    if (layout.current.bottom) node.scrollTop = node.scrollHeight
    else if (layout.current.anchor) {
      const { id, offset } = layout.current.anchor
      const anchor = node.querySelector(`[data-message-id="${id}"]`)
      if (anchor) node.scrollTop += anchor.getBoundingClientRect().top - node.getBoundingClientRect().top - offset
    }
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
