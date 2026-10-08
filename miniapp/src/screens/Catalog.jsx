import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../api'
import { Field } from '../fields'
import { Photo } from '../photo'
import { StoreIcon } from '../StoreIcon'
import { SORT_OPTIONS, catalogPrice, discountPercent, hasFreshStatus, hasSaleStatus, sortProducts } from '../catalogModel'
import { SortSheet } from './SortSheet'
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
  const [categories, setCategories] = useState([])
  const [subcategories, setSubcategories] = useState([])
  const [subcategory, setSubcategory] = useState(initialState.subcategory ?? null)
  const [ungrouped, setUngrouped] = useState(initialState.ungrouped || false)
  const [products, setProducts] = useState(null)
  const [active, setActive] = useState(initialState.active ?? null)
  const [search, setSearch] = useState(initialState.search || '')
  const [sort, setSort] = useState(initialState.sort || 'default')
  const [inStock, setInStock] = useState(initialState.inStock || false)
  const [sorting, setSorting] = useState(false)
  const [error, setError] = useState('')
  const [loadFailed, setLoadFailed] = useState(false)
  const [retry, setRetry] = useState(0)
  const searchRef = useRef(null)
  const closeSort = useCallback(() => setSorting(false), [])

  useEffect(() => {
    onStateChange?.({ active, subcategory, ungrouped, search, sort, inStock })
  }, [active, subcategory, ungrouped, search, sort, inStock, onStateChange])

  useEffect(() => {
    if (searchRequest) {
      searchRef.current?.querySelector('input')?.focus()
      onSearchRequestHandled?.(0)
    }
  }, [searchRequest, onSearchRequestHandled])
  useEffect(() => {
    let cancelled = false
    Promise.all([api.categories(), api.subcategories()]).then(([cats, subs]) => { if (!cancelled) { setCategories(cats); setSubcategories(subs) } }).catch((e) => !cancelled && setError(e.message))
    return () => { cancelled = true }
  }, [])
  useEffect(() => {
    let cancelled = false
    setProducts(null)
    setError('')
    setLoadFailed(false)
    const timer = setTimeout(() => {
      api.products({ categoryId: active, subcategoryId: subcategory, uncategorized: ungrouped, search: search.trim() || undefined })
        .then((rows) => !cancelled && setProducts(rows))
        .catch((e) => {
          if (!cancelled) { setProducts([]); setError(e.message); setLoadFailed(true) }
        })
    }, search ? 300 : 0)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [active, subcategory, ungrouped, search, retry])

  const change = async (product, delta) => {
    haptic('light')
    try { await onCartChange(product.id, delta) } catch (err) { setError(err.message) }
  }
  const view = useMemo(() => products === null ? null : sortProducts(products, sort, inStock), [products, sort, inStock])
  const hasFreshProducts = useMemo(() => (products || []).some(hasFreshStatus), [products])
  const filtered = sort !== 'default' || inStock || ungrouped || Boolean(search.trim())
  const chooseCategory = (id) => { setActive(id); setSubcategory(null); setUngrouped(false) }
  const visibleSubs = subcategories.filter((s) => active === null || s.category_id === active || s.category_id === null)
  const reset = () => {
    setSearch('')
    setSort('default')
    setInStock(false)
    setUngrouped(false)
  }
  const qtyOf = (id) => cart?.lines?.find((l) => l.product_id === id)?.qty || 0
  const savedIds = new Set((wishlists || []).flatMap((w) => w.product_ids || []))
  const sortLabel = SORT_OPTIONS.find((option) => option.value === sort)?.label

  return (
    <section className="store-catalog" aria-label="Каталог товарів">
      <div className="field search catalog-search" ref={searchRef}>
        <Field value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Назва або артикул (SKU)" aria-label="Пошук товарів" inputMode="search" />
        {search && <button className="search-clear" onClick={() => setSearch('')} aria-label="Очистити">✕</button>}
      </div>
      <div className="rail store-categories" role="group" aria-label="Категорії" tabIndex={0}>
        <button className="chip" aria-pressed={active === null} onClick={() => chooseCategory(null)}>Усе</button>
        {categories.map((c) => <button key={c.id} className="chip" aria-pressed={active === c.id} onClick={() => chooseCategory(c.id)}>{c.name}</button>)}
      </div>
      {visibleSubs.length > 0 && <div className="rail store-subcategories" role="group" aria-label="Субкатегорії" tabIndex={0}>
        <button className="chip" aria-pressed={subcategory === null} onClick={() => setSubcategory(null)}>Усі субкатегорії</button>
        {visibleSubs.map((s) => <button key={s.id} className="chip" aria-pressed={subcategory === s.id} onClick={() => { setSubcategory(s.id); setUngrouped(false) }}>{s.name}</button>)}
      </div>}
      <div className="store-catalog-tools">
        <div className="rail store-filter-rail" role="group" aria-label="Фільтри" tabIndex={0}>
          <button className="chip" aria-pressed={ungrouped} onClick={() => { setUngrouped((on) => !on); setActive(null); setSubcategory(null) }}>Без груп</button>
          <button className="chip" aria-pressed={inStock} onClick={() => setInStock((on) => !on)}>В наявності</button>
          {filtered && <button className="chip" onClick={reset}>Скинути фільтри</button>}
        </div>
        <button className="store-sort-button" onClick={() => setSorting(true)} aria-haspopup="dialog" aria-expanded={sorting} aria-label={`Сортування: ${sortLabel}`}><span>{sortLabel}</span><StoreIcon name="sort" /></button>
      </div>
      {error && <div className="banner warn" role="alert">{error}</div>}
      {products === null ? <div className="product-grid" aria-label="Завантаження товарів" aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton store-card-loading" />)}</div>
        : loadFailed ? <div className="empty"><h2>Не вдалося завантажити каталог</h2><p>Перевірте зʼєднання та повторіть спробу.</p><button className="secondary" onClick={() => setRetry((value) => value + 1)}>Повторити</button></div>
        : view.length === 0 ? <div className="empty"><h2>Нічого не знайшли</h2><p>{inStock && products.length > 0 ? 'Усе з цього переліку зараз закінчилось.' : search ? 'Спробуйте іншу назву або оберіть категорію.' : sort !== 'default' ? 'За цими фільтрами немає товарів.' : 'У цій категорії поки порожньо.'}</p>{filtered && <div className="actions"><button className="secondary" onClick={reset}>Скинути пошук і фільтри</button></div>}</div>
        : <><p className="store-found" aria-live="polite">{view.length === products.length ? `${view.length} ${plural(view.length)}` : `${view.length} із ${products.length}`}</p><div className="product-grid">{view.map((p) => <ProductCard key={p.id} product={p} qty={qtyOf(p.id)} currency={config.currency} onChange={change} onOpen={onOpenProduct} saved={savedIds.has(p.id)} onSave={onSave} />)}</div></>}
      {sorting && <SortSheet value={sort} hasFreshProducts={hasFreshProducts} onSelect={setSort} onClose={closeSort} />}
    </section>
  )
}
