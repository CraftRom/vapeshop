import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useProductImage } from '../components/catalog/useProductImage'
import NewProductModal from '../components/catalog/NewProductModal'
import TaxonomyManager from '../components/catalog/TaxonomyManager'

import { api } from '../api'
import { useFilters } from '../components/useFilters'
import { Empty, ErrorBar, Field, Loading, Modal, confirmPurge, money, useToast } from '../components/ui'

const SORT_OPTIONS = [
  ['name-asc', 'За назвою (А → Я)'],
  ['name-desc', 'За назвою (Я → А)'],
  ['stock-asc', 'Залишок: спочатку менше'],
  ['stock-desc', 'Залишок: спочатку більше'],
  ['price-asc', 'Ціна: спочатку дешевші'],
  ['price-desc', 'Ціна: спочатку дорожчі'],
]

function ProductThumb({ product }) {
  const [image] = useProductImage(product)
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [image])
  const initials = product.name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()

  if (!image || failed) {
    return (
      <div className="catalog-thumb catalog-thumb-fallback" aria-hidden="true">
        {initials || '•'}
      </div>
    )
  }

  return (
    <img
      className="catalog-thumb"
      src={image}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  )
}

function ProductStatus({ product }) {
  let tone = 'ok'
  let label = 'В наявності'

  if (!product.is_active) {
    tone = 'hidden'
    label = 'Прихований'
  } else if (product.stock === 0) {
    tone = 'bad'
    label = 'Немає'
  } else if (product.stock < 5) {
    tone = 'warn'
    label = 'Закінчується'
  }

  return <span className={`catalog-status ${tone}`}>{label}</span>
}


function sortedCatalog(products, sort) {
  const list = [...products]
  const byName = (a, b) => a.name.localeCompare(b.name, 'uk', { sensitivity: 'base' })

  switch (sort) {
    case 'name-desc': return list.sort((a, b) => -byName(a, b))
    case 'stock-asc': return list.sort((a, b) => a.stock - b.stock || byName(a, b))
    case 'stock-desc': return list.sort((a, b) => b.stock - a.stock || byName(a, b))
    case 'price-asc': return list.sort((a, b) => Number(a.price) - Number(b.price) || byName(a, b))
    case 'price-desc': return list.sort((a, b) => Number(b.price) - Number(a.price) || byName(a, b))
    default: return list.sort(byName)
  }
}

function paginationNumbers(current, total) {
  if (total <= 3) return Array.from({ length: total }, (_, index) => index + 1)
  const start = Math.max(1, Math.min(current - 1, total - 2))
  return [start, start + 1, start + 2]
}

function ImportProductsModal({ onClose, onDone }) {
  const [file, setFile] = useState(null)
  const [mode, setMode] = useState('upsert')
  const [prices, setPrices] = useState('none')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const run = async () => {
    if (!file) return
    setBusy(true); setError(''); setResult(null)
    try {
      const form=new FormData(); form.append('file',file); form.append('mode',mode); form.append('prices',prices)
      const res=await api.products.importXlsx(form); setResult(res); onDone()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <Modal title="Імпорт товарів із SalesDrive" onClose={onClose} footer={<><button className="btn ghost" onClick={onClose}>Закрити</button><button className="btn" disabled={!file||busy} onClick={run}>{busy?'Імпортую…':'Імпортувати'}</button></>}>
    <div className="stack">
      <ErrorBar error={error}/>
      <Field label="XLSX файл" hint="Підтримується стандартний експорт товарів SalesDrive."><input className="input" type="file" accept=".xlsx" onChange={e=>setFile(e.target.files?.[0]||null)}/></Field>
      <Field label="Що робити з товарами">
        <select className="input" value={mode} onChange={e=>setMode(e.target.value)}><option value="add">Тільки додавати нові</option><option value="update">Тільки оновлювати наявні</option><option value="upsert">Додати нові + перезаписати наявні</option></select>
      </Field>
      <Field label="Ціни" hint="За замовчуванням ціни в нашій базі взагалі не змінюються.">
        <select className="input" value={prices} onChange={e=>setPrices(e.target.value)}><option value="none">Не імпортувати ціни</option><option value="regular">Тільки звичайна ціна</option><option value="discount">Ціна зі знижкою + звичайна в поле «Стара ціна»</option><option value="both">Обидві ціни</option></select>
      </Field>
      <div className="muted">Товари звіряються за системним SKU або зовнішнім артикулом. Кожен новий товар отримує автоматичний SKU ELF-…; при оновленні артикул зберігається. Колонка «Категорія» старого експорту SalesDrive стає субкатегорією. Новий товар без імпорту ціни створюється прихованим з ціною 0, щоб випадково не потрапити у продаж.</div>
      {result && <div className="card"><strong>Готово</strong><div>Рядків: {result.rows} · додано: {result.created} · оновлено: {result.updated} · пропущено: {result.skipped}</div><div>Згенеровано SKU: {result.sku_generated} · змінено цін: {result.prices_changed}</div>{result.errors?.length>0 && <div className="bad">Помилок: {result.errors.length}. Перший рядок: {result.errors[0].row} — {result.errors[0].error}</div>}</div>}
    </div>
  </Modal>
}

export default function Catalog() {
  const location = useLocation(), navigate = useNavigate()
  const catalogBack = location.pathname + location.search
  const loadSequence = useRef(0)
  const notify = useToast()
  const [categories, setCategories] = useState([])
  const [subcategories, setSubcategories] = useState([])
  const [products, setProducts] = useState(null)
  // Категорія, пошук і сортування живуть в адресі: менеджер може
  // повернутися зі сторінки товару або надіслати колезі саме цей відбір.
  const [{ category, subcategory, feature, search, sort }, setQuery, resetFilters] = useFilters(
    { category: '', subcategory: '', feature: '', search: '', sort: 'name-asc' },
  )
  const filter = category
  const setFilter = (value) => setQuery('category', value)
  const setSearch = (value) => setQuery('search', value)
  const setSort = (value) => setQuery('sort', value)

  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [managingCategories, setManagingCategories] = useState(false)
  const [importing, setImporting] = useState(false)
  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(() => new Set())
  const [bulkAction, setBulkAction] = useState('')
  const [bulkBusy, setBulkBusy] = useState(false)
  const stockQueueRef = useRef(new Map())

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current
    setError('')
    try {
      const [cats, subs, prods] = await Promise.all([
        api.categories.list(), api.subcategories.list(),
        api.products.list({ category_id: filter || undefined, subcategory_id: subcategory || undefined, search: search || undefined, is_new: feature === 'new' ? true : undefined, is_sale: feature === 'sale' ? true : undefined, uncategorized: feature === 'ungrouped' ? true : undefined }),
      ])
      if (sequence !== loadSequence.current) return
      setCategories(cats); setSubcategories(subs)
      setProducts(prods)
    } catch (err) {
      if (sequence === loadSequence.current) setError(err.message)
    }
  }, [filter, subcategory, feature, search])

  useEffect(() => {
    const timer = setTimeout(load, search ? 350 : 0)
    return () => { clearTimeout(timer); loadSequence.current += 1 }
  }, [load, search])

  useEffect(() => {
    setPage(1)
    setSelected(new Set())
  }, [filter, subcategory, feature, search, sort, pageSize])

  const updateStock = (product, delta) => {
    // Кожен товар має власну Promise-чергу. Серверний delta атомарний, а
    // черга гарантує порядок відповідей: без неї два швидкі "+" могли
    // завершитись n+2, а потім запізніла відповідь n+1 відмалювала старий
    // залишок, хоча в БД уже все правильно.
    const previous = stockQueueRef.current.get(product.id) || Promise.resolve()
    const current = previous.catch(() => null).then(async () => {
      try {
        const updated = await api.products.adjustStock(product.id, delta)
        setProducts((list) => list.map((p) => (p.id === updated.id ? updated : p)))
      } catch (err) {
        notify(err.message, 'bad')
        await load()
      }
    })
    stockQueueRef.current.set(product.id, current)
    current.finally(() => {
      if (stockQueueRef.current.get(product.id) === current) stockQueueRef.current.delete(product.id)
    })
    return current
  }

  const purgeProduct = async (product) => {
    if (!confirmPurge(product.name)) return
    try {
      await api.products.purge(product.id)
      notify('Товар стерто назавжди')
      setSelected((current) => {
        const next = new Set(current)
        next.delete(product.id)
        return next
      })
      load()
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  const hide = async (product) => {
    if (!confirm(`Прибрати «${product.name}» з каталогу? Історія замовлень збережеться.`)) return
    try {
      await api.products.remove(product.id)
      notify('Товар прибрано з каталогу')
      setSelected((current) => {
        const next = new Set(current)
        next.delete(product.id)
        return next
      })
      load()
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  const show = async (product) => {
    try {
      const updated = await api.products.patch(product.id, { is_active: true })
      setProducts((list) => list.map((p) => (p.id === updated.id ? updated : p)))
      notify('Товар повернуто в каталог')
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  const ordered = products ? sortedCatalog(products, sort) : []
  const pageCount = Math.max(1, Math.ceil(ordered.length / pageSize))
  const safePage = Math.min(page, pageCount)
  const pageStart = (safePage - 1) * pageSize
  const visibleProducts = ordered.slice(pageStart, pageStart + pageSize)
  const visibleIds = visibleProducts.map((p) => p.id)
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id))

  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  const toggleSelected = (id) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleVisible = () => {
    setSelected((current) => {
      const next = new Set(current)
      const select = !visibleIds.every((id) => next.has(id))
      visibleIds.forEach((id) => (select ? next.add(id) : next.delete(id)))
      return next
    })
  }

  const runBulk = async () => {
    if (!bulkAction || selected.size === 0 || bulkBusy) return
    const chosen = (products || []).filter((p) => selected.has(p.id))
    if (chosen.length === 0) return

    if (bulkAction === 'hide' && !confirm(
      `Прибрати з каталогу вибрані товари (${chosen.length} шт)? Історія замовлень збережеться.`,
    )) return

    setBulkBusy(true)
    try {
      const targets = chosen.filter((p) => bulkAction === 'hide' ? p.is_active : !p.is_active)
      const results = await Promise.allSettled(targets.map((p) => api.products.patch(p.id, { is_active: bulkAction === 'show' })))
      const failed = results.filter((r) => r.status === 'rejected')
      notify(`Оновлено: ${results.length - failed.length}${failed.length ? ` · Помилки: ${failed.length}` : ''}`, failed.length ? 'bad' : 'ok')
      setSelected(new Set())
      setBulkAction('')
      await load()
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setBulkBusy(false)
    }
  }

  return (
    <>
      <div className="page-head catalog-page-head">
        <div>
          <h1>Каталог</h1>
          <p>Товари, категорії й відображення на вітрині та в боті</p>
        </div>
        <div className="catalog-head-actions">
          <button className="btn ghost" onClick={() => api.products.exportXlsx().catch(e => notify(e.message, 'bad'))}>Експорт XLSX</button>
          <button className="btn ghost" onClick={() => setImporting(true)}>Імпорт XLSX</button>
          <button
            className="btn ghost catalog-categories-btn"
            onClick={() => setManagingCategories(true)}
            title="Керувати категоріями"
          >
            <span className="catalog-categories-wide">Категорії</span>
            <span className="catalog-categories-short" aria-hidden="true">▦</span>
          </button>
          <button className="btn catalog-add-btn" onClick={() => setEditing({})}>
            <span aria-hidden="true">＋</span>
            <span className="catalog-add-wide">Додати товар</span>
            <span className="catalog-add-short">Додати</span>
          </button>
        </div>
      </div>

      <div className="catalog-toolbar">
        <label className="catalog-filter">
          <span>Категорія</span>
          <select className="input" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">Усі категорії</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.products_count})</option>
            ))}
          </select>
        </label>

        <label className="catalog-filter">
          <span>Пошук</span>
          <div className="catalog-search-box">
            <span className="catalog-search-icon" aria-hidden="true">⌕</span>
            <input
              className="input"
              placeholder="Пошук за назвою або SKU..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </label>

        <div className="catalog-toolbar-meta">
          <span className="catalog-found">
            Знайдено товарів: <strong>{products?.length ?? '—'}</strong>
          </span>
          <label className="catalog-sort">
            <span className="catalog-sort-title">Сортування</span>
            <select className="input" value={sort} onChange={(e) => setSort(e.target.value)}>
              {SORT_OPTIONS.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="catalog-extra-filters">
        <label><span>Субкатегорія</span><select className="input" aria-label="Фільтр субкатегорії" value={subcategory} onChange={(e) => setQuery('subcategory', e.target.value)}><option value="">Усі субкатегорії</option>{subcategories.map((s) => <option key={s.id} value={s.id}>{s.name}{s.category_name ? ` · ${s.category_name}` : ''}</option>)}</select></label>
        <label><span>Відображення</span><select className="input" aria-label="Фільтр відображення" value={feature} onChange={(e) => setQuery('feature', e.target.value)}><option value="">Усі товари</option><option value="new">Новинки</option><option value="sale">Акції</option><option value="ungrouped">Без категорій і субкатегорій</option></select></label>
      </div>
      <ErrorBar error={error} />

      {!products ? (
        <Loading />
      ) : products.length === 0 ? (
        (category || subcategory || feature || search) ? (
          <Empty title="Нічого не знайдено">
            За цим відбором товарів немає. Можливо, вони в іншій категорії.
            <div style={{ marginTop: 12 }}>
              <button className="btn ghost small" onClick={resetFilters}>
                Показати всі товари
              </button>
            </div>
          </Empty>
        ) : (
          <Empty title="Товарів немає">
            Додайте перший товар — він одразу зʼявиться в каталозі бота.
          </Empty>
        )
      ) : (
        <section className="catalog-panel" aria-label="Список товарів">
          <div className="catalog-list-head">
            <label className="catalog-check">
              <input
                type="checkbox"
                checked={allVisibleSelected}
                onChange={toggleVisible}
                aria-label="Вибрати товари на цій сторінці"
              />
            </label>
            <span>Товар</span>
            <span>Категорія</span>
            <span>Ціна</span>
            <span>Залишок</span>
            <span>Статус</span>
            <span>Дії</span>
          </div>

          <div className="catalog-list">
            {visibleProducts.map((p) => (
              <article className="catalog-product" key={p.id}>
                <label className="catalog-check catalog-row-check">
                  <input
                    type="checkbox"
                    checked={selected.has(p.id)}
                    onChange={() => toggleSelected(p.id)}
                    aria-label={`Вибрати ${p.name}`}
                  />
                </label>

                <div className="catalog-product-main">
                  <ProductThumb product={p} />
                  <div className="catalog-product-copy">
                    <Link className="catalog-product-link" to={`/catalog/products/${p.id}`} state={{ catalogBack }}><strong title={p.name}>{p.name}</strong></Link>
                    <span className="mono muted" style={{fontSize: 12}}>{p.sku}</span>
                    {p.description && <p>{p.description}</p>}
                    <span className="catalog-mobile-category">{[p.category_name, p.subcategory_name].filter(Boolean).join(" / ") || "Без груп"}</span>
                  </div>
                </div>

                <div className="catalog-category muted">{[p.category_name, p.subcategory_name].filter(Boolean).join(" / ") || "Без груп"}</div>

                <div className="catalog-price">
                  <strong>{money(p.price)}</strong>
                  {p.is_sale && p.old_price && <s>{money(p.old_price)}</s>}
                </div>

                <div className="catalog-stock" aria-label={`Залишок ${p.stock}`}>
                  <button
                    className="catalog-stepper"
                    onClick={() => updateStock(p, -1)}
                    disabled={p.stock <= 0}
                    aria-label={`Зменшити залишок ${p.name}`}
                  >
                    −
                  </button>
                  <span className="mono">{p.stock}</span>
                  <button
                    className="catalog-stepper"
                    onClick={() => updateStock(p, 1)}
                    aria-label={`Збільшити залишок ${p.name}`}
                  >
                    +
                  </button>
                </div>

                <div className="catalog-status-cell">
                  <ProductStatus product={p} /><div className="catalog-flags">{p.is_new && <span className="chip ok">Новинка</span>}{p.is_sale && <span className="chip">Акція</span>}</div>
                </div>

                <div className="catalog-actions">
                  <Link className="btn small catalog-edit" to={`/catalog/products/${p.id}`} state={{ catalogBack }}>
                    <span aria-hidden="true">✎</span> Відкрити
                  </Link>
                  {p.is_active ? (
                    <button
                      className="btn ghost small catalog-visibility"
                      onClick={() => hide(p)}
                      title="Зникне з бота, лишиться в історії"
                    >
                      Прибрати
                    </button>
                  ) : (
                    <button
                      className="btn ghost small catalog-visibility"
                      onClick={() => show(p)}
                    >
                      Показати
                    </button>
                  )}
                  <button
                    className="btn danger small"
                    onClick={() => purgeProduct(p)}
                    title="Стерти з бази назавжди. Необоротно"
                  >
                    Стерти
                  </button>
                </div>
              </article>
            ))}
          </div>

          <footer className="catalog-footer">
            <div className="catalog-bulk">
              <span>Вибрано: <strong>{selected.size}</strong></span>
              <select
                className="input"
                value={bulkAction}
                onChange={(e) => setBulkAction(e.target.value)}
                disabled={selected.size === 0}
              >
                <option value="">Дія з вибраними</option>
                <option value="hide">Прибрати з каталогу</option>
                <option value="show">Показати в каталозі</option>
              </select>
              <button
                className="btn ghost small"
                disabled={!bulkAction || selected.size === 0 || bulkBusy}
                onClick={runBulk}
              >
                {bulkBusy ? 'Виконую…' : 'Застосувати'}
              </button>
            </div>

            <div className="catalog-pagination">
              <label>
                <span>Показати:</span>
                <select
                  className="input"
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                >
                  <option value={10}>10</option>
                  <option value={20}>20</option>
                  <option value={50}>50</option>
                </select>
              </label>
              <button
                className="catalog-page-btn"
                disabled={safePage <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                aria-label="Попередня сторінка"
              >
                ‹
              </button>
              {paginationNumbers(safePage, pageCount).map((number) => (
                <button
                  key={number}
                  className={`catalog-page-btn ${safePage === number ? 'active' : ''}`}
                  onClick={() => setPage(number)}
                >
                  {number}
                </button>
              ))}
              {pageCount > 3 && <span className="catalog-page-more">…</span>}
              <button
                className="catalog-page-btn"
                disabled={safePage >= pageCount}
                onClick={() => setPage((value) => Math.min(pageCount, value + 1))}
                aria-label="Наступна сторінка"
              >
                ›
              </button>
              <span className="catalog-total">з {ordered.length} товарів</span>
            </div>
          </footer>
        </section>
      )}

      {importing && <ImportProductsModal onClose={() => setImporting(false)} onDone={load} />}

      {editing && <NewProductModal categories={categories} subcategories={subcategories} onClose={() => setEditing(null)} onSaved={(product) => navigate(`/catalog/products/${product.id}`, { state: { catalogBack } })} />}
      {managingCategories && <TaxonomyManager categories={categories} subcategories={subcategories} onClose={() => setManagingCategories(false)} onChanged={load} />}

    </>
  )
}
