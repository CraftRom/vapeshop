import { StoreIcon } from './StoreIcon'

const sections = [
  ['catalog', 'Каталог'], ['search', 'Пошук'], ['cart', 'Кошик'],
  ['chat', 'Чат'], ['profile', 'Профіль'],
]

export function StoreNavigation({ active, count, onNavigate }) {
  return (
    <nav className="store-nav" aria-label="Розділи магазину">
      {sections.map(([id, label]) => (
        // Name from the content, in the order it is shown ("Кошик 3"): an
        // aria-label without the visible count fails WCAG 2.5.3 Label in Name.
        <button key={id} onClick={() => onNavigate(id)} className="store-nav-link" aria-current={active === id ? 'page' : undefined}>
          <span>{label}</span>
          <span className="store-nav-symbol" aria-hidden="true"><StoreIcon name={id} /></span>
          {id === 'cart' && count > 0 && <span className="store-nav-count">{count > 99 ? '99+' : count}</span>}
        </button>
      ))}
    </nav>
  )
}
