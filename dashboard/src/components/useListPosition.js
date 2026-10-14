import { useLayoutEffect, useRef } from 'react'
const positions = new Map()
export function useListPosition(key, ready) {
  const restored = useRef(null)
  useLayoutEffect(() => {
    const save = () => {
      if (restored.current === key) positions.set(key, window.scrollY)
      if (positions.size > 50) positions.delete(positions.keys().next().value)
    }
    window.addEventListener('scroll', save, { passive: true })
    return () => { save(); window.removeEventListener('scroll', save) }
  }, [key])
  useLayoutEffect(() => {
    if (!ready || restored.current === key) return
    window.scrollTo({ top: positions.get(key) || 0, behavior: 'instant' })
    restored.current = key
  }, [key, ready])
}
