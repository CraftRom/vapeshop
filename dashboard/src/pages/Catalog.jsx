import { useCallback, useEffect, useState } from 'react'
import ImageField from '../components/ImageField'

import { api } from '../api'
import { useFilters } from '../components/useFilters'
import { Empty, ErrorBar, Field, Loading, Modal, confirmPurge, money, useToast } from '../components/ui'

const EMPTY_PRODUCT = {
  category_id: '',
  name: '',
  description: '',
  price: '',
  old_price: '',
  stock: 0,
  photo_url: '',
  sort_order: 0,
  is_active: true,
}

function ProductForm({ product, categories, onClose, onSaved }) {
  const notify = useToast()
  const [form, setForm] = useState({ ...EMPTY_PRODUCT, ...product })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }

  const save = async () => {
    setBusy(true)
    setError('')
    const payload = {
      ...form,
      category_id: Number(form.category_id),
      price: Number(form.price),
      old_price: form.old_price ? Number(form.old_price) : null,
      stock: Number(form.stock),
      sort_order: Number(form.sort_order),
      photo_url: form.photo_url || null,
      description: form.description || null,
    }
    try {
      const saved = product?.id
        ? await api.products.update(product.id, payload)
        : await api.products.create(payload)
      onSaved(saved)
      notify(product?.id ? 'Товар оновлено' : 'Товар додано')
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const valid = form.name.trim() && form.category_id && Number(form.price) > 0

  return (
    <Modal
      title={product?.id ? 'Редагувати товар' : 'Новий товар'}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Скасувати</button>
          <button className="btn" onClick={save} disabled={busy || !valid}>Зберегти</button>
        </>
      }
    >
      <div className="stack">
        <ErrorBar error={error} />
        <Field label="Назва">
          <input className="input" value={form.name} onChange={set('name')} autoFocus />
        </Field>
        <Field label="Категорія">
          <select className="input" value={form.category_id} onChange={set('category_id')}>
            <option value="">Оберіть категорію</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Опис" hint="Показується в картці товару в боті">
          <textarea className="input" value={form.description || ''} onChange={set('description')} />
        </Field>
        <div className="grid k3">
          <Field label="Ціна, ₴">
            <input className="input" type="number" min="0" value={form.price} onChange={set('price')} />
          </Field>
          <Field label="Стара ціна" hint="Для показу знижки">
            <input className="input" type="number" min="0" value={form.old_price || ''} onChange={set('old_price')} />
          </Field>
          <Field label="Залишок, шт">
            <input className="input" type="number" min="0" value={form.stock} onChange={set('stock')} />
          </Field>
        </div>
        <ImageField
          label="Фото товару"
          value={form.photo_url || ''}
          onChange={(url) => setForm((f) => ({ ...f, photo_url: url }))}
          hint="Показується в картці товару в боті та вітрині. JPG, PNG, WebP або GIF, до 5 МБ."
        />
        <div className="row">
          <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
            <input type="checkbox" checked={form.is_active} onChange={set('is_active')} />
            Показувати в каталозі
          </label>
        </div>
      </div>
    </Modal>
  )
}

function CategoryForm({ category, onClose, onSaved }) {
  const notify = useToast()
  const editing = Boolean(category?.id)
  const [form, setForm] = useState({
    name: category?.name || '',
    sort_order: category?.sort_order ?? 0,
    is_active: category?.is_active ?? true,
  })
  const [error, setError] = useState('')

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }

  const save = async () => {
    const payload = {
      name: form.name.trim(),
      sort_order: Number(form.sort_order) || 0,
      is_active: form.is_active,
    }
    try {
      const saved = editing
        ? await api.categories.update(category.id, payload)
        : await api.categories.create(payload)
      onSaved(saved)
      notify(editing ? 'Категорію оновлено' : 'Категорію створено')
      onClose()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <Modal
      title={editing ? 'Редагувати категорію' : 'Нова категорія'}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Скасувати</button>
          <button className="btn" onClick={save} disabled={!form.name.trim()}>
            {editing ? 'Зберегти' : 'Створити'}
          </button>
        </>
      }
    >
      <ErrorBar error={error} />
      <Field label="Назва категорії">
        <input className="input" value={form.name} onChange={set('name')} autoFocus />
      </Field>
      <Field label="Порядок" hint="Менше число — вище у списку в боті">
        <input className="input" type="number" value={form.sort_order} onChange={set('sort_order')} />
      </Field>
      <div className="row">
        <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
          <input type="checkbox" checked={form.is_active} onChange={set('is_active')} />
          Показувати в боті
        </label>
      </div>
    </Modal>
  )
}

function CategoryManager({ categories, onClose, onChanged }) {
  const notify = useToast()
  const [editing, setEditing] = useState(null)

  const remove = async (category) => {
    const warning = category.products_count > 0
      ? ` Разом із нею з каталогу зникнуть товари (${category.products_count} шт).`
      : ''
    if (!confirm(
      `Прибрати категорію «${category.name}» з каталогу?${warning}` +
      ' Історія замовлень збережеться.'
    )) return
    try {
      const res = await api.categories.remove(category.id)
      const hidden = res?.hidden_products || 0
      notify(hidden
        ? `Категорію прибрано, разом із нею ${hidden} товар(ів)`
        : 'Категорію прибрано з каталогу')
      onChanged()
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  const purge = async (category) => {
    const extra = category.products_count > 0
      ? `Разом з нею назавжди зникнуть товари (${category.products_count} шт).`
      : ''
    if (!confirmPurge(category.name, extra)) return
    try {
      const res = await api.categories.purge(category.id)
      notify(`Стерто назавжди${res?.purged_products ? `, товарів: ${res.purged_products}` : ''}`)
      onChanged()
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  return (
    <>
      <Modal
        title="Категорії"
        onClose={onClose}
        footer={
          <>
            <button className="btn ghost" onClick={onClose}>Закрити</button>
            <button className="btn" onClick={() => setEditing({})}>Нова категорія</button>
          </>
        }
      >
        {categories.length === 0 ? (
          <Empty title="Категорій немає">
            Створіть першу — без неї товар не додати.
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Назва</th>
                  <th className="num">Порядок</th>
                  <th className="num">Товарів</th>
                  <th>Статус</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {categories.map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}</td>
                    <td className="num">{c.sort_order}</td>
                    <td className="num">{c.products_count}</td>
                    <td>
                      <span className={`chip ${c.is_active ? 'ok' : ''}`}>
                        {c.is_active ? 'Активна' : 'Прихована'}
                      </span>
                    </td>
                    <td>
                      <div className="row">
                        <button className="btn small ghost" onClick={() => setEditing(c)}>
                          Змінити
                        </button>
                        <button
                          className="btn danger small"
                          onClick={() => remove(c)}
                          title="Приховати: зникне з бота, лишиться в базі"
                        >
                          Приховати
                        </button>
                        <button
                          className="btn danger small"
                          onClick={() => purge(c)}
                          title="Стерти з бази назавжди. Необоротно"
                        >
                          Стерти
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Modal>

      {editing && (
        <CategoryForm
          category={editing.id ? editing : null}
          onClose={() => setEditing(null)}
          onSaved={onChanged}
        />
      )}
    </>
  )
}

const SORT_OPTIONS = [
  ['name-asc', 'За назвою (А → Я)'],
  ['name-desc', 'За назвою (Я → А)'],
  ['stock-asc', 'Залишок: спочатку менше'],
  ['stock-desc', 'Залишок: спочатку більше'],
  ['price-asc', 'Ціна: спочатку дешевші'],
  ['price-desc', 'Ціна: спочатку дорожчі'],
]

function ProductThumb({ product }) {
  const [failed, setFailed] = useState(false)
  const initials = product.name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase()

  if (!product.photo_url || failed) {
    return (
      <div className="catalog-thumb catalog-thumb-fallback" aria-hidden="true">
        {initials || '•'}
      </div>
    )
  }

  return (
    <img
      className="catalog-thumb"
      src={product.photo_url}
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

function productPayload(product, overrides = {}) {
  return {
    category_id: Number(product.category_id),
    name: product.name,
    description: product.description || null,
    price: Number(product.price),
    old_price: product.old_price ? Number(product.old_price) : null,
    stock: Number(product.stock),
    photo_url: product.photo_url || null,
    sort_order: Number(product.sort_order) || 0,
    is_active: Boolean(product.is_active),
    ...overrides,
  }
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

export default function Catalog() {
  const notify = useToast()
  const [categories, setCategories] = useState([])
  const [products, setProducts] = useState(null)
  // Категорія, пошук і сортування живуть в адресі: менеджер може
  // повернутися зі сторінки товару або надіслати колезі саме цей відбір.
  const [{ category, search, sort }, setQuery, resetFilters] = useFilters(
    { category: '', search: '', sort: 'name-asc' },
  )
  const filter = category
  const setFilter = (value) => setQuery('category', value)
  const setSearch = (value) => setQuery('search', value)
  const setSort = (value) => setQuery('sort', value)

  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [managingCategories, setManagingCategories] = useState(false)
  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(() => new Set())
  const [bulkAction, setBulkAction] = useState('')
  const [bulkBusy, setBulkBusy] = useState(false)

  const load = useCallback(async () => {
    setError('')
    try {
      const [cats, prods] = await Promise.all([
        api.categories.list(),
        api.products.list({ category_id: filter || undefined, search: search || undefined }),
      ])
      setCategories(cats)
      setProducts(prods)
    } catch (err) {
      setError(err.message)
    }
  }, [filter, search])

  useEffect(() => {
    const timer = setTimeout(load, search ? 350 : 0)
    return () => clearTimeout(timer)
  }, [load, search])

  useEffect(() => {
    setPage(1)
    setSelected(new Set())
  }, [filter, search, sort, pageSize])

  const updateStock = async (product, stock) => {
    try {
      const updated = await api.products.setStock(product.id, Math.max(0, stock))
      setProducts((list) => list.map((p) => (p.id === updated.id ? updated : p)))
    } catch (err) {
      notify(err.message, 'bad')
    }
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
      const updated = await api.products.update(
        product.id,
        productPayload(product, { is_active: true }),
      )
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
      if (bulkAction === 'hide') {
        await Promise.all(chosen.filter((p) => p.is_active).map((p) => api.products.remove(p.id)))
        notify(`Прибрано товарів: ${chosen.filter((p) => p.is_active).length}`)
      } else if (bulkAction === 'show') {
        await Promise.all(chosen.filter((p) => !p.is_active).map((p) => (
          api.products.update(p.id, productPayload(p, { is_active: true }))
        )))
        notify(`Повернуто товарів: ${chosen.filter((p) => !p.is_active).length}`)
      }
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
          <p>Товари, ціни та залишки — усе, що бачить клієнт у боті</p>
        </div>
        <div className="catalog-head-actions">
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
        <label className="catalog-filter catalog-category-filter">
          <span>Категорія</span>
          <select className="input" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">Усі категорії</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.products_count})</option>
            ))}
          </select>
        </label>

        <label className="catalog-filter catalog-search-filter">
          <span>Пошук</span>
          <div className="catalog-search-box">
            <span className="catalog-search-icon" aria-hidden="true">⌕</span>
            <input
              className="input"
              placeholder="Пошук за назвою товару..."
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

      <ErrorBar error={error} />

      {!products ? (
        <Loading />
      ) : products.length === 0 ? (
        (category || search) ? (
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
                    <strong title={p.name}>{p.name}</strong>
                    {p.description && <p>{p.description}</p>}
                    <span className="catalog-mobile-category">{p.category_name}</span>
                  </div>
                </div>

                <div className="catalog-category muted">{p.category_name}</div>

                <div className="catalog-price">
                  <strong>{money(p.price)}</strong>
                  {p.old_price && <s>{money(p.old_price)}</s>}
                </div>

                <div className="catalog-stock" aria-label={`Залишок ${p.stock}`}>
                  <button
                    className="catalog-stepper"
                    onClick={() => updateStock(p, p.stock - 1)}
                    disabled={p.stock <= 0}
                    aria-label={`Зменшити залишок ${p.name}`}
                  >
                    −
                  </button>
                  <span className="mono">{p.stock}</span>
                  <button
                    className="catalog-stepper"
                    onClick={() => updateStock(p, p.stock + 1)}
                    aria-label={`Збільшити залишок ${p.name}`}
                  >
                    +
                  </button>
                </div>

                <div className="catalog-status-cell">
                  <ProductStatus product={p} />
                </div>

                <div className="catalog-actions">
                  <button className="btn small catalog-edit" onClick={() => setEditing(p)}>
                    <span aria-hidden="true">✎</span> Змінити
                  </button>
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
                    className="btn danger small catalog-delete"
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
                  className={`catalog-page-btn catalog-page-number ${safePage === number ? 'active' : ''}`}
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

      {editing && (
        <ProductForm
          product={editing.id ? editing : null}
          categories={categories}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}

      {managingCategories && (
        <CategoryManager
          categories={categories}
          onClose={() => setManagingCategories(false)}
          onChanged={load}
        />
      )}
    </>
  )
}
