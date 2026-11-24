import { useId } from 'react'

// Page building blocks (UI/UX audit UI-007). Every page reads the same way:
// title → context → filters/actions → content. The components only fix the
// structure and semantics; business state stays in the pages.

/**
 * Page title, one sentence of context and the page-level actions.
 * `actions` is rendered as is, so a page keeps its own buttons and handlers.
 */
export function PageHeader({ title, description, actions, className = '' }) {
  return (
    <header className={`page-head ${className}`.trim()}>
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions}
    </header>
  )
}

/**
 * A titled card. The heading names the region for screen readers, `actions`
 * sit on the heading row (a module switch, "Show all"), `description` explains
 * what the section is responsible for.
 */
export function SectionCard({ title, description, actions, children, className = '', level = 2 }) {
  const headingId = useId()
  const Heading = `h${level}`
  return (
    <section className={`card section-card ${className}`.trim()} aria-labelledby={headingId}>
      <div className="section-card-head">
        <Heading id={headingId}>{title}</Heading>
        {actions}
      </div>
      {description && <p className="faint section-card-description">{description}</p>}
      {children}
    </section>
  )
}

/**
 * Search and filter controls of a list. The group is named so assistive
 * technology announces what it filters; the reset button appears only when
 * something is actually filtered and says how many filters it clears.
 */
export function FilterBar({ label, children, activeCount = 0, onReset, className = '' }) {
  return (
    <div className={`filter-bar ${className}`.trim()} role="group" aria-label={label}>
      {children}
      {onReset && activeCount > 0 && (
        <button type="button" className="btn ghost small filter-bar-reset" onClick={onReset}>
          Скинути фільтри ({activeCount})
        </button>
      )}
    </div>
  )
}

/**
 * What the list is filtered by, one removable chip per filter, plus the
 * result count. `items`: [{ key, label, onClear }]. Renders nothing when
 * nothing is filtered, so an unfiltered list carries no extra row.
 */
export function ActiveFilters({ items, count, onResetAll, label = 'Активні фільтри' }) {
  if (!items.length) return null
  return (
    <div className="active-filters" role="region" aria-label={label}>
      {count !== undefined && count !== null && <span className="active-filters-count" role="status">Знайдено: <strong>{count}</strong></span>}
      <ul>
        {items.map((item) => (
          <li key={item.key}>
            <button type="button" className="active-filter-chip" onClick={item.onClear} aria-label={`Прибрати фільтр: ${item.label}`}>
              <span>{item.label}</span>
              <span aria-hidden="true">✕</span>
            </button>
          </li>
        ))}
      </ul>
      {onResetAll && items.length > 1 && (
        <button type="button" className="btn ghost small" onClick={onResetAll}>Скинути всі</button>
      )}
    </div>
  )
}
