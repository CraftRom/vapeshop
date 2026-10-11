import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../api'
import { Field } from '../fields'
import { Photo } from '../photo'
import { StoreIcon } from '../StoreIcon'
import { DEFAULT_SORT, SORT_OPTIONS, catalogPrice, discountPercent, hasFreshStatus, hasSaleStatus, sortProducts, normalizeCatalogState, resolveCatalogState, loadCatalogProducts } from '../catalogModel'
import { SortSheet } from './SortSheet'
import { CategoryNavigator } from './CategoryNavigator'
import { close, haptic } from '../telegram'

/** Той самий 18+ бар'єр, що й у боті. Каталог до підтвердження недоступний. */
export function AgeGate({ config, onConfirmed }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const age = config?.min_age ?? 18

  const confirm = async () => {
    setBusy(true)
    try {
      const updated = await api.confirmAge()
      onConfirmed(updated)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="gate">
      <div className="gate-mark">{age}+</div>
      <h1>Підтвердження віку</h1>
      <p>
        Товари містять нікотин і продаються лише особам, яким виповнилося {age} років.
      </p>
      <p>
        Нікотин викликає залежність. Продукція не є засобом для відмови від куріння.
      </p>
      {error && <div className="banner warn">{error}</div>}
      <div className="actions">
        <button className="primary" onClick={confirm} disabled={busy}>
          {busy ? 'Хвилинку…' : `Мені є ${age}`}
        </button>
        <button className="secondary" onClick={close}>
          Мені менше — вийти
        </button>
      </div>
    </div>
  )
}

function plural(count) {
  const tail = count % 100
  if (tail >= 11 && tail <= 14) return 'товарів'
  if (count % 10 === 1) return 'товар'
  if (count % 10 >= 2 && count % 10 <= 4) return 'товари'
  return 'товарів'
}

function stockLabel(stock) {
  if (stock <= 0) return <span className="stock out">Закінчився</span>
  if (stock < 5) return <span className="stock low">Залишилось {stock}</span>
  return <span className="stock">В наявності</span>
}

/** Shared by catalog, wishlists and recently viewed products. */
export function ProductCard({ product, qty = 0, currency, onChange, onOpen, saved, onSave, saveLabel }) {
  const out = product.stock <= 0
  const oldPrice = Number(product.old_price || 0)
  const discounted = hasSaleStatus(product)
  const discount = discountPercent(product)
  return (
    <article className={`store-card ${out ? 'is-out' : ''}`}>
      <div className="store-card-media">
        <button className="store-card-photo" onClick={() => onOpen(product)} aria-label={`Відкрити ${product.name}`}>
          <span className="photo-placeholder"><StoreIcon name="box" /></span>
          <Photo key={product.id} product={product} className="store-card-image" />
        </button>
        {discount > 0 && <span className="store-card-discount">−{discount}%</span>}
        {hasFreshStatus(product) && <span className={`store-card-new ${discount > 0 ? 'with-discount' : ''}`}>Новинка</span>}
        {onSave && <button className={`store-card-save store-icon-button ${saved ? 'is-saved' : ''} ${saveLabel ? 'with-label' : ''}`} onClick={() => onSave(product)} aria-label={saveLabel || (saved ? 'У списку бажаного' : 'Відкласти')} title={saveLabel || (saved ? 'У списку бажаного' : 'Відкласти')}>
          {saveLabel || <StoreIcon name="heart" filled={saved} />}
        </button>}
      </div>
      <button className="store-card-title" onClick={() => onOpen(product)}>{product.name}</button>
      <div className="store-card-stock">{stockLabel(product.stock)}</div>
      <div className="store-card-bottom">
        <div className="store-card-price num">
          {discounted && <span className="old-price">{catalogPrice(oldPrice)} {currency}</span>}
          <strong>{catalogPrice(product.price)} {currency}</strong>
        </div>
        {qty === 0 && <button className="store-card-add store-icon-button" disabled={out} onClick={() => onChange(product, 1)} aria-label={`Додати в кошик: ${product.name}`}><StoreIcon name="cart" /></button>}
      </div>
      {qty > 0 && <div className="stepper store-card-stepper">
        <button onClick={() => onChange(product, -1)} aria-label="Прибрати одну штуку">−</button>
        <span className="qty num" aria-live="polite">{qty}</span>
        <button onClick={() => onChange(product, 1)} disabled={out || qty >= product.stock} aria-label="Додати ще одну штуку">+</button>
      </div>}
    </article>
  )
}

export function Catalog({ config, cart, onCartChange, onOpenProduct, wishlists, onSave, searchRequest = 0, initialState = {}, onStateChange, onSearchRequestHandled }) {
  const [selection, setSelection] = useState(() => normalizeCatalogState(initialState))
  const { active, subcategory, ungrouped, search, sort, inStock } = selection
  const [taxonomy, setTaxonomy] = useState(null)
  const [taxonomyError, setTaxonomyError] = useState('')
  const [taxonomyRetry, setTaxonomyRetry] = useState(0)
  const [products, setProducts] = useState(null)
  const [sorting, setSorting] = useState(false)
  const [error, setError] = useState('')
  const [loadFailed, setLoadFailed] = useState(false)
  const [retry, setRetry] = useState(0)
  const searchRef = useRef(null)
  const closeSort = useCallback(() => setSorting(false), [])
  const update = (patch) => setSelection((state) => ({ ...state, ...patch }))

  useEffect(() => {
    if (taxonomy) onStateChange?.(selection)
  }, [selection, taxonomy, onStateChange])

  useEffect(() => {
    if (searchRequest) {
      searchRef.current?.querySelector('input')?.focus()
      onSearchRequestHandled?.(0)
    }
  }, [searchRequest, onSearchRequestHandled])
  useEffect(() => {
    let cancelled = false
    setTaxonomyError('')
    Promise.all([api.categories(), api.subcategories()]).then(([cats, subs]) => {
      if (cancelled) return
      const categories = cats.map((item) => ({ ...item, id: Number(item.id) }))
      const subcategories = subs.map((item) => ({ ...item, id: Number(item.id), category_id: item.category_id == null ? null : Number(item.category_id) }))
      setSelection((state) => resolveCatalogState(state, categories, subcategories))
      setTaxonomy({ categories, subcategories })
    }).catch((err) => { if (!cancelled) setTaxonomyError(err.message) })
    return () => { cancelled = true }
  }, [taxonomyRetry])
  useEffect(() => {
    // Resolve restored group IDs before the first products request.
    if (!taxonomy) return
    let cancelled = false
    setProducts(null)
    setError('')
    setLoadFailed(false)
    const timer = setTimeout(() => {
      loadCatalogProducts(api.products, { categoryId: active, subcategoryId: subcategory, uncategorized: ungrouped, search: search.trim() || undefined }, () => cancelled)
        .then((rows) => { if (!cancelled) setProducts(rows) })
        .catch((err) => {
          if (!cancelled) { setProducts([]); setError(err.message); setLoadFailed(true) }
        })
    }, search.trim() ? 300 : 0)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [active, subcategory, ungrouped, search, retry, taxonomy])

  const change = async (product, delta) => {
    haptic('light')
    try { await onCartChange(product.id, delta) } catch (err) { setError(err.message) }
  }
  const view = useMemo(() => products === null ? null : sortProducts(products, sort, inStock), [products, sort, inStock])
  const narrowed = inStock || ungrouped || active !== null || subcategory !== null || Boolean(search.trim())
  const filtered = narrowed || sort !== DEFAULT_SORT
  const chooseCategory = (id) => update({ active: id, subcategory: null, ungrouped: false })
  const chooseSubcategory = (sub) => update({ active: sub.category_id, subcategory: sub.id, ungrouped: false })
  const chooseUngrouped = (value) => update({ ungrouped: value, active: null, subcategory: null })
  const reset = () => setSelection(normalizeCatalogState())
  const clearRefinements = () => update({ search: '', inStock: false })
  const qtyOf = (id) => cart?.lines?.find((line) => line.product_id === id)?.qty || 0
  const savedIds = new Set((wishlists || []).flatMap((list) => list.product_ids || []))
  const sortLabel = SORT_OPTIONS.find((option) => option.value === sort)?.label
  const refinementActive = inStock || Boolean(search.trim())

  return (
    <section className="store-catalog" aria-label="Каталог товарів">
      <div className="field search catalog-search" ref={searchRef}>
        <Field value={search} onChange={(event) => update({ search: event.target.value })} placeholder="Назва або артикул (SKU)" aria-label="Пошук товарів" inputMode="search" />
        {search && <button className="search-clear" onClick={() => update({ search: '' })} aria-label="Очистити">✕</button>}
      </div>
      {taxonomyError ? <div className="catalog-taxonomy-error banner warn" role="alert"><p>Не вдалося завантажити категорії: {taxonomyError}</p><button className="secondary" onClick={() => setTaxonomyRetry((value) => value + 1)}>Повторити завантаження категорій</button></div>
        : taxonomy ? <CategoryNavigator {...taxonomy} active={active} subcategory={subcategory} ungrouped={ungrouped} onCategory={chooseCategory} onSubcategory={chooseSubcategory} onUngrouped={chooseUngrouped} />
        : <p className="store-found" role="status">Завантажуємо категорії…</p>}
      <div className="store-catalog-tools">
        <div className="rail store-filter-rail" role="group" aria-label="Фільтри" tabIndex={0}>
          <button className="chip" aria-pressed={ungrouped} onClick={() => chooseUngrouped(!ungrouped)}>Без груп</button>
          <button className="chip" aria-pressed={inStock} onClick={() => update({ inStock: !inStock })}>В наявності</button>
          {filtered && <button className="chip" onClick={reset}>Скинути фільтри</button>}
        </div>
        <button className="store-sort-button" onClick={() => setSorting(true)} aria-haspopup="dialog" aria-expanded={sorting} aria-label={`Сортування: ${sortLabel}`}><span>{sortLabel}</span><StoreIcon name="sort" /></button>
      </div>
      {refinementActive && <div className="catalog-active-filters" role="group" aria-label="Активні фільтри">
        {search.trim() && <button onClick={() => update({ search: '' })} aria-label="Прибрати фільтр пошуку"><span>Пошук: {search.trim()}</span><StoreIcon name="close" /></button>}
        {inStock && <button onClick={() => update({ inStock: false })} aria-label="Прибрати фільтр наявності"><span>Лише в наявності</span><StoreIcon name="close" /></button>}
      </div>}
      {error && <div className="banner warn" role="alert">{error}</div>}
      {taxonomyError && !taxonomy ? null : products === null ? <div className="product-grid" aria-label="Завантаження товарів" aria-busy="true">{[0, 1, 2, 3].map((id) => <div key={id} className="skeleton store-card-loading" />)}</div>
        : loadFailed ? <div className="empty"><h2>Не вдалося завантажити каталог</h2><p>Перевірте зʼєднання та повторіть спробу.</p><button className="secondary" onClick={() => setRetry((value) => value + 1)}>Повторити</button></div>
        : view.length === 0 ? <div className="empty"><StoreIcon name="search" /><h2>Нічого не знайшли</h2><p>{inStock && products.length > 0 ? 'Усе з цього переліку зараз закінчилось.' : refinementActive ? 'У вибраному розділі немає товарів за цими умовами. Змініть пошук або фільтри.' : narrowed ? 'У цьому розділі поки немає товарів. Перегляньте іншу категорію.' : 'Асортимент скоро зʼявиться.'}</p><div className="actions">{refinementActive && <button className="secondary" onClick={clearRefinements}>Показати всі товари розділу</button>}{filtered && <button className="secondary" onClick={reset}>Скинути пошук і фільтри</button>}</div></div>
        : <><div className="catalog-results-heading"><p className="store-found" aria-live="polite">{view.length} {plural(view.length)}</p>{(sort === 'fresh' || sort === 'sale') && <p className="catalog-order-note">{sort === 'fresh' ? 'Новинки першими, далі весь асортимент' : 'Акції першими, далі весь асортимент'}</p>}</div><div className="product-grid">{view.map((product) => <ProductCard key={product.id} product={product} qty={qtyOf(product.id)} currency={config.currency} onChange={change} onOpen={onOpenProduct} saved={savedIds.has(product.id)} onSave={onSave} />)}</div></>}
      {sorting && <SortSheet value={sort} onSelect={(value) => update({ sort: value })} onClose={closeSort} />}
    </section>
  )
}
