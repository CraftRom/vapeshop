import { Children, cloneElement, isValidElement, useState } from 'react'
import { Modal } from './ui'

const nodes = (value) => Children.toArray(value).filter(isValidElement)
function textOf(value) {
  return Children.toArray(value).map((item) => isValidElement(item) ? textOf(item.props.children) : String(item)).join('')
}
export function ManagedTable({ tableId, label, children }) {
  const elements = nodes(children)
  const table = elements.find((item) => item.type === 'table')
  const sections = table ? nodes(table.props.children) : []
  const head = sections.find((item) => item.type === 'thead')
  const columns = head ? nodes(nodes(head.props.children)[0]?.props.children).map((cell) => textOf(cell.props.children)) : []
  const storageKey = `elfar.table.columns.${tableId}`
  const [hidden, setHidden] = useState(() => {
    try { const value = JSON.parse(localStorage.getItem(storageKey)); return Array.isArray(value) ? value.filter((x) => typeof x === 'string') : [] } catch { return [] }
  })
  const [open, setOpen] = useState(false)
  const update = (next) => {
    setHidden(next)
    try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch { /* optional preference */ }
  }
  const rendered = table && cloneElement(table, {}, sections.map((section) => {
    if (!['thead', 'tbody', 'tfoot'].includes(section.type)) return section
    return cloneElement(section, {}, nodes(section.props.children).map((row) => cloneElement(row, {},
      nodes(row.props.children).map((cell, index) => cloneElement(cell, { hidden: index > 0 && hidden.includes(columns[index]) })),
    )))
  }))
  return <section className="managed-table" aria-label={label}>
    <div className="managed-table-tools"><span className="faint">{label}</span><button className="btn ghost small" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>Колонки: {label}</button></div>
    <div className="table-wrap managed-table-scroll" tabIndex={0} role="region" aria-label={`Таблиця: ${label}`}>{rendered}{elements.filter((item) => item !== table)}</div>
    {open && <Modal title={`Колонки: ${label}`} onClose={() => setOpen(false)} footer={<><button className="btn ghost" onClick={() => update([])}>Показати всі</button><button className="btn" onClick={() => setOpen(false)}>Готово</button></>}>
      <p className="faint">Перший стовпець завжди видимий. Вибір зберігається в цьому браузері.</p>
      <div className="table-column-options">{columns.map((name, index) => <label key={`${index}:${name}`}><input type="checkbox" checked={index === 0 || !hidden.includes(name)} disabled={index === 0} onChange={(event) => update(event.target.checked ? hidden.filter((x) => x !== name) : [...hidden, name])} />{name}</label>)}</div>
    </Modal>}
  </section>
}
