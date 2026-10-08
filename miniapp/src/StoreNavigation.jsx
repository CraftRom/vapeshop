import { StoreIcon } from './StoreIcon'

const sections = [
  ['catalog', 'Каталог'], ['search', 'Пошук'], ['cart', 'Кошик'],
  ['chat', 'Чат'], ['profile', 'Профіль'],
]

export function StoreNavigation({ active, count, onNavigate }) {
  return (
    <nav className="store-nav" aria-label="Розділи магазину">
      {sections.map(([id, label]) => (
        <button key={id} className="store-nav-link" aria-current={active === id ? 'page' : undefined} onClick={() => onNavigate(id)}>
          <span className="store-nav-symbol"><StoreIcon name={id} />{id === 'cart' && count > 0 && <span className="store-nav-count" aria-label={`${count} у кошику`}>{count > 99 ? '99+' : count}</span>}</span>
          <span>{label}</span>
        </button>
      ))}
    </nav>
  )
}
