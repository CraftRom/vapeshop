import { useCallback, useEffect, useRef, useState } from 'react'
import { StoreIcon } from '../StoreIcon'
import { Field } from '../fields'
import { mountDialog } from '../dialog'
import { backButton } from '../telegram'

function GroupCount({ group }) {
  return Number.isFinite(group.products_count) ? <span className="taxonomy-count" aria-label={`Кількість товарів: ${group.products_count}`}>{group.products_count}</span> : null
}

function CategoryPicker({ categories, subcategories, active, subcategory, ungrouped, onCategory, onSubcategory, onUngrouped, onClose }) {
  const ref = useRef(null)
  const [query, setQuery] = useState('')
  useEffect(() => mountDialog(ref.current, onClose), [onClose])
  useEffect(() => { backButton(onClose); return () => backButton(null) }, [onClose])
  const matches = (group) => group.name.toLocaleLowerCase('uk').includes(query.trim().toLocaleLowerCase('uk'))
  const roots = categories.filter((group) => matches(group) || subcategories.some((sub) => sub.category_id === group.id && matches(sub)))
  const independent = subcategories.filter((group) => group.category_id === null && matches(group))
  const select = (callback, value) => { callback(value); onClose() }
  return <div className="sheet-backdrop" onClick={onClose}>
    <section className="sheet category-sheet" ref={ref} role="dialog" aria-modal="true" aria-labelledby="category-picker-title" tabIndex={-1} onClick={(event) => event.stopPropagation()}>
      <div className="category-sheet-head"><div><p className="taxonomy-eyebrow">Знайдіть свій розділ</p><h2 id="category-picker-title">Категорії та підкатегорії</h2></div><button className="store-icon-button" onClick={onClose} aria-label="Закрити категорії"><StoreIcon name="close" /></button></div>
      <div className="field category-search"><Field value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Знайти категорію" aria-label="Пошук категорій" inputMode="search" /></div>
      {!query.trim() && <div className="category-quick-actions"><button aria-pressed={active === null && subcategory === null && !ungrouped} onClick={() => select(onCategory, null)}><StoreIcon name="catalog" />Усі товари</button><button aria-pressed={ungrouped} onClick={() => select(onUngrouped, true)}><StoreIcon name="box" />Без груп</button></div>}
      <div className="category-tree">
        {roots.map((group) => <div className="category-tree-group" key={group.id}>
          <button className="category-tree-root" aria-label={group.name} aria-pressed={active === group.id && subcategory === null && !ungrouped} onClick={() => select(onCategory, group.id)}><span>{group.name}</span><GroupCount group={group} /><StoreIcon name="forward" /></button>
          <div className="category-tree-children">{subcategories.filter((sub) => sub.category_id === group.id && (matches(group) || matches(sub))).map((sub) => <button key={sub.id} aria-label={sub.name} aria-pressed={subcategory === sub.id && !ungrouped} onClick={() => select(onSubcategory, sub)}><span>{sub.name}</span><GroupCount group={sub} />{subcategory === sub.id && <StoreIcon name="check" />}</button>)}</div>
        </div>)}
        {independent.length > 0 && <div className="category-tree-group"><h3>Самостійні групи</h3><div className="category-tree-children is-independent">{independent.map((sub) => <button key={sub.id} aria-label={sub.name} aria-pressed={subcategory === sub.id && !ungrouped} onClick={() => select(onSubcategory, sub)}><span>{sub.name}</span><GroupCount group={sub} />{subcategory === sub.id && <StoreIcon name="check" />}</button>)}</div></div>}
        {!roots.length && !independent.length && <p className="category-search-empty" role="status">Категорій за цим запитом немає. Спробуйте іншу назву.</p>}
      </div>
    </section>
  </div>
}

export function CategoryNavigator({ categories, subcategories, active, subcategory, ungrouped, onCategory, onSubcategory, onUngrouped }) {
  const [open, setOpen] = useState(false)
  const railRef = useRef(null), subsRef = useRef(null)
  const close = useCallback(() => setOpen(false), [])
  const category = categories.find((group) => group.id === active)
  const sub = subcategories.find((group) => group.id === subcategory)
  const independent = subcategories.filter((group) => group.category_id === null)
  const visibleSubs = active === null ? [] : subcategories.filter((group) => group.category_id === active)
  useEffect(() => {
    // Reveal a restored selection using horizontal scroll only; keep the page position.
    for (const rail of [railRef.current, subsRef.current]) {
      const selected = rail?.querySelector('[aria-pressed="true"]')
      if (!selected) continue
      const box = selected.getBoundingClientRect(), viewport = rail.getBoundingClientRect()
      if (box.left < viewport.left) rail.scrollLeft -= viewport.left - box.left + 16
      else if (box.right > viewport.right) rail.scrollLeft += box.right - viewport.right + 16
    }
  }, [active, subcategory, ungrouped, categories, subcategories])
  return <div className="catalog-taxonomy">
    <div className="taxonomy-heading"><h2>Категорії</h2><button className="taxonomy-browse" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open}>Усі категорії<StoreIcon name="catalog" /></button></div>
    <div ref={railRef} className="rail store-categories" role="group" aria-label="Категорії" tabIndex={0}>
      <button className="category-tile" aria-label="Усе" aria-pressed={active === null && subcategory === null && !ungrouped} onClick={() => onCategory(null)}><span className="category-tile-symbol"><StoreIcon name="catalog" /></span><span className="category-tile-name">Усе</span><span className="category-tile-detail">Весь асортимент</span></button>
      {categories.map((group) => <button key={group.id} className="category-tile" aria-label={group.name} aria-pressed={active === group.id && !ungrouped} onClick={() => onCategory(group.id)}><span className="category-tile-symbol"><StoreIcon name="box" /></span><span className="category-tile-name">{group.name}</span><span className="category-tile-detail"><GroupCount group={group} />{subcategories.some((sub) => sub.category_id === group.id) ? 'Є підкатегорії' : 'Переглянути'}</span></button>)}
      {independent.map((group) => <button key={`sub-${group.id}`} className="category-tile" aria-label={group.name} aria-pressed={subcategory === group.id && !ungrouped} onClick={() => onSubcategory(group)}><span className="category-tile-symbol"><StoreIcon name="box" /></span><span className="category-tile-name">{group.name}</span><span className="category-tile-detail"><GroupCount group={group} />Самостійна група</span></button>)}
    </div>
    {(category || sub || ungrouped) && <nav className="taxonomy-breadcrumb" aria-label="Шлях категорії"><button onClick={() => onCategory(null)}>Усі товари</button>{category && <><StoreIcon name="forward" /><button onClick={() => onCategory(category.id)} aria-current={!sub ? 'page' : undefined}>{category.name}</button></>}{(sub || ungrouped) && <><StoreIcon name="forward" /><span aria-current="page">{sub?.name || 'Без груп'}</span></>}</nav>}
    {!ungrouped && visibleSubs.length > 0 && <div className="taxonomy-subsection"><p className="taxonomy-eyebrow">{category ? `У розділі «${category.name}»` : 'Самостійні групи'}</p><div ref={subsRef} className="rail store-subcategories" role="group" aria-label="Субкатегорії" tabIndex={0}>
      <button className="chip" aria-label="Усі субкатегорії" aria-pressed={subcategory === null} onClick={() => onCategory(active)}>{category ? 'Усі товари розділу' : 'Усі товари'}</button>
      {visibleSubs.map((group) => <button key={group.id} className="chip" aria-label={group.name} aria-pressed={subcategory === group.id} onClick={() => onSubcategory(group)}><span>{group.name}</span><GroupCount group={group} /></button>)}
    </div></div>}
    {open && <CategoryPicker categories={categories} subcategories={subcategories} active={active} subcategory={subcategory} ungrouped={ungrouped} onCategory={onCategory} onSubcategory={onSubcategory} onUngrouped={onUngrouped} onClose={close} />}
  </div>
}
