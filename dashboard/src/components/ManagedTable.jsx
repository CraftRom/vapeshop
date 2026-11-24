import { Children, cloneElement, isValidElement, useState } from 'react'
import { Modal } from './ui'

const nodes = (value) => Children.toArray(value).filter(isValidElement)
function textOf(value) {
  return Children.toArray(value).map((item) => isValidElement(item) ? textOf(item.props.children) : String(item)).join('')
}

/**
 * Column identity (UI-016). A header cell may name its column with
 * `data-column="roas"`; that id survives renamed or translated headers.
 * Without it the header text is used. Repeated ids get a «#2», «#3» suffix,
 * so two columns with the same caption are hidden independently.
 */
export function columnIds(headerCells) {
  const seen = new Map()
  return headerCells.map((cell) => {
    const base = String(cell.props['data-column'] || textOf(cell.props.children)).trim() || 'column'
    const count = (seen.get(base) || 0) + 1
    seen.set(base, count)
    return count === 1 ? base : `${base}#${count}`
  })
}

const storageKey = (tableId) => `elfar.table.columns.v2.${tableId}`
const legacyKey = (tableId) => `elfar.table.columns.${tableId}`

/**
 * Hidden columns of this table in this browser. Older versions stored header
 * texts under the elfar.* key; they are mapped once to the current ids and
 * moved to the new key, so a saved choice is not lost by the upgrade.
 */
export function readHidden(tableId, columns, headers) {
  const strings = (value) => (Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [])
  try {
    const saved = localStorage.getItem(storageKey(tableId))
    if (saved !== null) return strings(JSON.parse(saved))
    const legacy = strings(JSON.parse(localStorage.getItem(legacyKey(tableId))))
    if (!legacy.length) return []
    const migrated = columns.filter((id, index) => legacy.includes(headers[index]))
    localStorage.setItem(storageKey(tableId), JSON.stringify(migrated))
    localStorage.removeItem(legacyKey(tableId))
    return migrated
  } catch {
    return []
  }
}

export function ManagedTable({ tableId, label, children }) {
  const elements = nodes(children)
  const table = elements.find((item) => item.type === 'table')
  const sections = table ? nodes(table.props.children) : []
  const head = sections.find((item) => item.type === 'thead')
  const headerCells = head ? nodes(nodes(head.props.children)[0]?.props.children) : []
  const headers = headerCells.map((cell) => textOf(cell.props.children))
  const columns = columnIds(headerCells)
  const [hidden, setHidden] = useState(() => readHidden(tableId, columns, headers))
  const [open, setOpen] = useState(false)
  const update = (next) => {
    setHidden(next)
    try { localStorage.setItem(storageKey(tableId), JSON.stringify(next)) } catch { /* optional preference */ }
  }
  // The first (identity) column is never hidden, whatever was stored.
  const isHidden = (index) => index > 0 && hidden.includes(columns[index])
  const rendered = table && cloneElement(table, {}, sections.map((section) => {
    if (!['thead', 'tbody', 'tfoot'].includes(section.type)) return section
    return cloneElement(section, {}, nodes(section.props.children).map((row) => cloneElement(row, {},
      nodes(row.props.children).map((cell, index) => cloneElement(cell, { hidden: isHidden(index) })),
    )))
  }))
  return <section className="managed-table" aria-label={label}>
    <div className="managed-table-tools"><span className="faint">{label}</span><button className="btn ghost small" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>Колонки: {label}</button></div>
    <div className="table-wrap managed-table-scroll" tabIndex={0} role="region" aria-label={`Таблиця: ${label}`}>{rendered}{elements.filter((item) => item !== table)}</div>
    {open && <Modal title={`Колонки: ${label}`} onClose={() => setOpen(false)} footer={<><button className="btn ghost" onClick={() => update([])}>Показати всі</button><button className="btn" onClick={() => setOpen(false)}>Готово</button></>}>
      <p className="faint">Перший стовпець завжди видимий. Вибір зберігається в цьому браузері.</p>
      <div className="table-column-options">{columns.map((id, index) => <label key={id}><input type="checkbox" checked={!isHidden(index)} disabled={index === 0} onChange={(event) => update(event.target.checked ? hidden.filter((x) => x !== id) : [...hidden, id])} />{headers[index]}</label>)}</div>
    </Modal>}
  </section>
}
