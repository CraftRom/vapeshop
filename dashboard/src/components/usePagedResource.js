import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

// One gate for search, manual refresh, polling and live invalidations.
export function usePagedResource(key, fetchPage, delay = 0) {
  const generation = useRef(0)
  const currentKey = useRef(key)
  const [state, setState] = useState({ key, data: null, total: 0, loading: true, error: '' })
  useLayoutEffect(() => {
    currentKey.current = key
    generation.current += 1
    return () => { generation.current += 1 }
  }, [key])

  const load = useCallback(async () => {
    if (currentKey.current !== key) return
    const request = ++generation.current
    setState((prev) => prev.key === key
      ? { ...prev, loading: true }
      : { key, data: null, total: 0, loading: true, error: '' })
    try {
      const page = await fetchPage()
      if (request !== generation.current || currentKey.current !== key) return
      setState({ key, data: page.items, total: page.total, loading: false, error: '' })
    } catch (err) {
      if (request !== generation.current || currentKey.current !== key) return
      setState((prev) => ({ ...prev, loading: false, error: err.message || 'Не вдалося завантажити дані' }))
    }
  }, [key, fetchPage])

  useEffect(() => {
    const timer = setTimeout(load, delay)
    return () => clearTimeout(timer)
  }, [load, delay])

  const setData = useCallback((update) => setState((prev) => prev.key === key
    ? { ...prev, data: typeof update === 'function' ? update(prev.data) : update }
    : prev), [key])
  return state.key === key
    ? { ...state, load, setData }
    : { data: null, total: 0, loading: true, error: '', load, setData }
}
