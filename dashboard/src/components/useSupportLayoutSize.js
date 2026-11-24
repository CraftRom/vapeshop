import { useCallback, useEffect, useRef, useState } from 'react'

const WIDTH_KEY = 'elfar:support:inbox-width:v1'
const HEIGHT_KEY = 'elfar:support:chat-height:v1'
export const DEFAULT_INBOX_WIDTH = 360
export const DEFAULT_CHAT_HEIGHT = 620
const MIN_WIDTH = 240, MAX_WIDTH = 650
const MIN_HEIGHT = 440, MAX_HEIGHT = 1100
// The saved height is a preference; on a short screen the workspace shrinks
// to what is visible below its top so the composer is never off-screen.
const MIN_FIT_HEIGHT = 320, FIT_MARGIN = 12

export function clampSupportSize(value, min, max, fallback) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.max(min, Math.min(max, Math.round(parsed))) : fallback
}

function readSize(key, fallback, min, max) {
  try { return clampSupportSize(localStorage.getItem(key) ?? fallback, min, max, fallback) }
  catch { return fallback }
}

export function useSupportLayoutSize() {
  const containerRef = useRef(null)
  const pointer = useRef(null)
  const [width, setWidthValue] = useState(() => readSize(WIDTH_KEY, DEFAULT_INBOX_WIDTH, MIN_WIDTH, MAX_WIDTH))
  const [height, setHeightValue] = useState(() => readSize(HEIGHT_KEY, DEFAULT_CHAT_HEIGHT, MIN_HEIGHT, MAX_HEIGHT))
  const [maxWidth, setMaxWidth] = useState(MAX_WIDTH)
  const [fitHeight, setFitHeight] = useState(Infinity)
  useEffect(() => {
    const measure = () => {
      const top = containerRef.current ? containerRef.current.getBoundingClientRect().top + window.scrollY : 0
      setFitHeight(Math.max(MIN_FIT_HEIGHT, Math.floor(window.innerHeight - top - FIT_MARGIN)))
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])
  const calcMaxWidth = useCallback(() => {
    const bounds = containerRef.current?.getBoundingClientRect()
    // Leave space for the composer even if the inbox becomes wide.
    return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Math.round((bounds?.width || 1120) - 380)))
  }, [])
  useEffect(() => {
    const update = () => setMaxWidth(calcMaxWidth())
    update()
    if (typeof ResizeObserver !== 'undefined' && containerRef.current) {
      const observer = new ResizeObserver(update)
      observer.observe(containerRef.current)
      return () => observer.disconnect()
    }
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [calcMaxWidth])
  const setWidth = useCallback(value => setWidthValue(clampSupportSize(value, MIN_WIDTH, calcMaxWidth(), DEFAULT_INBOX_WIDTH)), [calcMaxWidth])
  const setHeight = useCallback(value => setHeightValue(clampSupportSize(value, MIN_HEIGHT, MAX_HEIGHT, DEFAULT_CHAT_HEIGHT)), [])
  useEffect(() => { try { localStorage.setItem(WIDTH_KEY, String(width)) } catch { /* optional preference */ } }, [width])
  useEffect(() => { try { localStorage.setItem(HEIGHT_KEY, String(height)) } catch { /* optional preference */ } }, [height])
  const beginResize = useCallback((event, axis) => {
    if (event.button !== 0 || window.matchMedia('(max-width: 760px)').matches) return
    event.preventDefault()
    pointer.current = { axis, pointerId: event.pointerId, x: event.clientX, y: event.clientY, width, height }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }, [width, height])
  const moveResize = useCallback(event => {
    const drag = pointer.current
    if (!drag || drag.pointerId !== event.pointerId) return
    if (drag.axis === 'width') setWidth(drag.width + event.clientX - drag.x)
    else setHeight(drag.height + event.clientY - drag.y)
  }, [setWidth, setHeight])
  const endResize = useCallback(event => {
    if (!pointer.current || event.pointerId !== pointer.current.pointerId) return
    pointer.current = null
    try { event.currentTarget.releasePointerCapture?.(event.pointerId) } catch { /* may already be released */ }
  }, [])
  const onKeyDown = useCallback((event, axis) => {
    const delta = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 20
      : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -20 : 0
    if (event.key === 'Home') {
      event.preventDefault()
      axis === 'width' ? setWidth(DEFAULT_INBOX_WIDTH) : setHeight(DEFAULT_CHAT_HEIGHT)
    } else if (delta && ((axis === 'width' && /Arrow(Left|Right)/.test(event.key)) ||
      (axis === 'height' && /Arrow(Up|Down)/.test(event.key)))) {
      event.preventDefault()
      axis === 'width' ? setWidth(width + delta) : setHeight(height + delta)
    }
  }, [width, height, setWidth, setHeight])
  // On phones the layout stacks and scrolls with the page: no fitting there.
  const appliedHeight = Math.min(height, fitHeight)
  return { containerRef, width, height, appliedHeight, maxWidth, setWidth, setHeight,
    beginResize, moveResize, endResize, onKeyDown }
}
