import { useCallback, useEffect, useRef, useState } from 'react'
import { StoreIcon } from '../StoreIcon'
import { Field } from '../fields'
import { mountDialog } from '../dialog'
import { backButton } from '../telegram'

function GroupCount({ group }) {
  return Number.isFinite(group.products_count) ? <span className="taxonomy-count" aria-label={`Кількість товарів: ${group.products_count}`}>{group.products_count}</span> : null
}

function CategoryTile({ name, selected, onClick, group, detail, icon = 'box' }) {
  return <button className="category-tile" aria-label={name} aria-pressed={selected} onClick={onClick}>
    <span className="category-tile-symbol"><StoreIcon name={icon} /></span>
    <span className="category-tile-name">{name}</span>
    <span className="category-tile-detail">{group && <GroupCount group={group} />}{detail}</span>
    {selected && <span className="category-tile-check"><StoreIcon name="check" /></span>}
  </button>
}

function CategoryPicker({ categories, subcategories, active, subcategory, ungrouped, onCategory, onSubcategory, onUngrouped, onClose }) {
  const ref = useRef(null)
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState(() => new Set(active === null ? [] : [active]))
  useEffect(() => mountDialog(ref.current, onClose), [onClose])
  useEffect(() => { backButton(onClose); return () => backButton(null) }, [onClose])
  const matches = (group) => group.name.toLocaleLowerCase('uk').includes(query.trim().toLocaleLowerCase('uk'))
  const roots = categories.filter((group) => matches(group) || subcategories.some((sub) => sub.category_id === group.id && matches(sub)))
  const independent = subcategories.filter((group) => group.category_id === null && matches(group))
  const select = (callback, value) => { callback(value); onClose() }
  const toggle = (id) => setExpanded((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next })
  return <div className="sheet-backdrop" onClick={onClose}>
    <section className="sheet category-sheet" ref={ref} role="dialog" aria-modal="true" aria-labelledby="category-picker-title" tabIndex={-1} onClick={(event) => event.stopPropagation()}>
      <div className="category-sheet-head"><div><p className="taxonomy-eyebrow">Оберіть потрібний розділ</p><h2 id="category-picker-title">Категорії та підкатегорії</h2></div><button className="store-icon-button" onClick={onClose} aria-label="Закрити категорії"><StoreIcon name="close" /></button></div>
      <div className="field category-search"><Field value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Категорія або підкатегорія" aria-label="Пошук категорій" inputMode="search" /></div>
      {!query.trim() && <div className="category-quick-actions"><button aria-pressed={active === null && subcategory === null && !ungrouped} onClick={() => select(onCategory, null)}><StoreIcon name="catalog" />Усі товари</button><button aria-pressed={ungrouped} onClick={() => select(onUngrouped, true)}><StoreIcon name="box" />Без категорії</button></div>}
      <div className="category-tree">
        {roots.map((group) => {
          const children = subcategories.filter((sub) => sub.category_id === group.id && (matches(group) || matches(sub)))
          const isExpanded = Boolean(query.trim()) || expanded.has(group.id)
          const childId = `category-children-${group.id}`
          return <div className="category-tree-group" key={group.id}>
            <div className="category-tree-row"><button className="category-tree-root" aria-label={group.name} aria-pressed={active === group.id && subcategory === null && !ungrouped} onClick={() => select(onCategory, group.id)}><StoreIcon name="box" /><span>{group.name}</span><GroupCount group={group} /></button>
              {children.length > 0 && <button className="category-tree-toggle store-icon-button" aria-label={`Підкатегорії: ${group.name}`} aria-expanded={isExpanded} aria-controls={childId} disabled={Boolean(query.trim())} onClick={() => toggle(group.id)}><span>{children.length}</span><StoreIcon name="forward" /></button>}
            </div>
            {children.length > 0 && <div id={childId} className="category-tree-children" hidden={!isExpanded}>{children.map((sub) => <button key={sub.id} aria-label={sub.name} aria-pressed={subcategory === sub.id && !ungrouped} onClick={() => select(onSubcategory, sub)}><span>{sub.name}</span><GroupCount group={sub} />{subcategory === sub.id && <StoreIcon name="check" />}</button>)}</div>}
          </div>
        })}
        {independent.length > 0 && <div className="category-tree-group"><h3>Інші категорії</h3><div className="category-tree-children is-independent">{independent.map((sub) => <button key={sub.id} aria-label={sub.name} aria-pressed={subcategory === sub.id && !ungrouped} onClick={() => select(onSubcategory, sub)}><StoreIcon name="box" /><span>{sub.name}</span><GroupCount group={sub} />{subcategory === sub.id && <StoreIcon name="check" />}</button>)}</div></div>}
        {!roots.length && !independent.length && <p className="category-search-empty" role="status">Категорій за цим запитом немає. Спробуйте іншу назву.</p>}
      </div>
    </section>
  </div>
}

export function CategoryNavigator({ categories, subcategories, active, subcategory, ungrouped, onCategory, onSubcategory, onUngrouped }) {
  const [open, setOpen] = useState(false)
  const [scroll, setScroll] = useState({ before: false, after: false })
  const railRef = useRef(null), subsRef = useRef(null)
  const close = useCallback(() => setOpen(false), [])
  const category = categories.find((group) => group.id === active)
  const sub = subcategories.find((group) => group.id === subcategory)
  const independent = subcategories.filter((group) => group.category_id === null)
  const visibleSubs = active === null ? [] : subcategories.filter((group) => group.category_id === active)
  useEffect(() => {
    const rail = railRef.current
    const measure = () => setScroll({ before: rail.scrollLeft > 2, after: rail.scrollLeft + rail.clientWidth < rail.scrollWidth - 2 })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(rail)
    rail.addEventListener('scroll', measure, { passive: true })
    return () => { observer.disconnect(); rail.removeEventListener('scroll', measure) }
  }, [categories, subcategories])
  useEffect(() => {
    // Reveal the selection horizontally without moving the page vertically.
    for (const rail of [railRef.current, subsRef.current]) {
      const selected = rail?.querySelector('[aria-pressed="true"]')
      if (!selected) continue
      const box = selected.getBoundingClientRect(), viewport = rail.getBoundingClientRect()
      if (box.left < viewport.left) rail.scrollLeft -= viewport.left - box.left + 16
      else if (box.right > viewport.right) rail.scrollLeft += box.right - viewport.right + 16
    }
  }, [active, subcategory, ungrouped, categories, subcategories])
  const move = (direction) => railRef.current?.scrollBy({ left: direction * railRef.current.clientWidth * .75, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
  return <div className="catalog-taxonomy">
    <div className="taxonomy-heading"><h2>Категорії</h2><div className="taxonomy-heading-actions">{(scroll.before || scroll.after) && <div className="taxonomy-scroll-buttons"><button className="store-icon-button" aria-label="Попередні категорії" disabled={!scroll.before} onClick={() => move(-1)}><StoreIcon name="back" /></button><button className="store-icon-button" aria-label="Наступні категорії" disabled={!scroll.after} onClick={() => move(1)}><StoreIcon name="forward" /></button></div>}<button className="taxonomy-browse" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open}>Усі категорії<StoreIcon name="catalog" /></button></div></div>
    <div ref={railRef} className="rail store-categories" role="group" aria-label="Категорії" tabIndex={0}>
      <CategoryTile name="Усе" icon="catalog" selected={active === null && subcategory === null && !ungrouped} onClick={() => onCategory(null)} detail="Весь асортимент" />
      {categories.map((group) => <CategoryTile key={group.id} name={group.name} group={group} selected={active === group.id && !ungrouped} onClick={() => onCategory(group.id)} detail={subcategories.some((sub) => sub.category_id === group.id) ? 'Є підкатегорії' : 'Переглянути товари'} />)}
      {independent.map((group) => <CategoryTile key={`sub-${group.id}`} name={group.name} group={group} selected={subcategory === group.id && !ungrouped} onClick={() => onSubcategory(group)} detail="Переглянути товари" />)}
      <CategoryTile name="Без категорії" selected={ungrouped} onClick={() => onUngrouped(true)} detail="Інші товари каталогу" />
    </div>
    {(category || sub || ungrouped) && <nav className="taxonomy-breadcrumb" aria-label="Шлях категорії"><button onClick={() => onCategory(null)}>Усі товари</button>{category && <><StoreIcon name="forward" /><button onClick={() => onCategory(category.id)} aria-current={!sub ? 'page' : undefined}>{category.name}</button></>}{(sub || ungrouped) && <><StoreIcon name="forward" /><span aria-current="page">{sub?.name || 'Без категорії'}</span></>}</nav>}
    {!ungrouped && visibleSubs.length > 0 && <div className="taxonomy-subsection"><p className="taxonomy-eyebrow">Підкатегорії · {category?.name}</p><div ref={subsRef} className="rail store-subcategories" role="group" aria-label="Субкатегорії" tabIndex={0}>
      <button className="chip" aria-label="Усі субкатегорії" aria-pressed={subcategory === null} onClick={() => onCategory(active)}>Усі товари розділу</button>
      {visibleSubs.map((group) => <button key={group.id} className="chip" aria-label={group.name} aria-pressed={subcategory === group.id} onClick={() => onSubcategory(group)}><span>{group.name}</span><GroupCount group={group} />{subcategory === group.id && <StoreIcon name="check" />}</button>)}
    </div></div>}
    {open && <CategoryPicker categories={categories} subcategories={subcategories} active={active} subcategory={subcategory} ungrouped={ungrouped} onCategory={onCategory} onSubcategory={onSubcategory} onUngrouped={onUngrouped} onClose={close} />}
  </div>
}
