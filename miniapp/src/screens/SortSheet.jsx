import { useEffect, useRef } from 'react'
import { mountDialog } from '../dialog'
import { SORT_OPTIONS } from '../catalogModel'
import { StoreIcon } from '../StoreIcon'
import { backButton } from '../telegram'

export function SortSheet({ value, hasFreshProducts, onSelect, onClose }) {
  const ref = useRef(null)
  useEffect(() => mountDialog(ref.current, onClose), [onClose])
  useEffect(() => {
    backButton(onClose)
    return () => { backButton(null) }
  }, [onClose])
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <section className="sheet sort-sheet" ref={ref} role="dialog" aria-modal="true" aria-labelledby="sort-heading" tabIndex={-1} onClick={(event) => event.stopPropagation()}>
        <div className="sort-sheet-head"><h2 id="sort-heading">Сортування товарів</h2><button className="store-icon-button" onClick={onClose} aria-label="Закрити сортування"><StoreIcon name="close" /></button></div>
        <div role="group" aria-label="Порядок товарів" className="sort-options">
          {SORT_OPTIONS.filter((option) => option.value !== 'fresh' || hasFreshProducts).map((option) => (
            <button key={option.value} className="sort-option" aria-pressed={value === option.value} onClick={() => { onSelect(option.value); onClose() }}>
              <span>{option.label}</span>{value === option.value && <StoreIcon name="check" />}
            </button>
          ))}
        </div>
      </section>
    </div>
  )
}
