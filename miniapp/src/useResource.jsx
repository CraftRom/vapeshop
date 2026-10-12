import { useCallback, useEffect, useRef, useState } from 'react'

// Failed reads keep the last successful value. All refresh paths share a gate.
export function useResource(fetchData, initial = null) {
  const sequence = useRef(0)
  const mounted = useRef(true)
  const [state, setState] = useState({ data: initial, loading: true, error: '' })
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; sequence.current += 1 }
  }, [])
  const read = useCallback(async () => {
    const request = ++sequence.current
    setState((prev) => ({ ...prev, loading: true }))
    try {
      const data = await fetchData()
      if (!mounted.current || request !== sequence.current) return null
      setState({ data, loading: false, error: '' })
      return data
    } catch (err) {
      if (mounted.current && request === sequence.current) {
        setState((prev) => ({ ...prev, loading: false, error: err.message || 'Не вдалося завантажити дані' }))
      }
      return null
    }
  }, [fetchData])
  const setData = useCallback((update) => {
    sequence.current += 1
    setState((prev) => ({ data: typeof update === 'function' ? update(prev.data) : update, loading: false, error: '' }))
  }, [])
  const invalidate = useCallback(() => { sequence.current += 1 }, [])
  return { ...state, read, setData, invalidate }
}

export function ResourceStatus({ resource, label }) {
  if (resource.error) return (
    <div className="banner warn" role="alert">
      <b>{label}: {resource.error}</b>
      <p>{resource.data === null ? 'Дані не завантажено.' : 'Показано попередні дані. Вони можуть бути застарілими.'}</p>
      <button className="secondary" disabled={resource.loading} onClick={resource.read}>Повторити: {label}</button>
    </div>
  )
  if (resource.loading) return <p className="hint" role="status">{resource.data === null ? 'Завантажуємо' : 'Оновлюємо'}: {label}…</p>
  return null
}
