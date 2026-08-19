import { useCallback, useEffect, useState } from 'react'

import { api } from '../api'
import { Empty, ErrorBar, Field, Loading, Modal, money, useToast } from '../components/ui'

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
        <Field label="Посилання на фото" hint="Пряме посилання на зображення (jpg/png)">
          <input className="input" value={form.photo_url || ''} onChange={set('photo_url')} />
        </Field>
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
    if (category.products_count > 0) {
      notify(
        `У категорії «${category.name}» ще ${category.products_count} товар(ів). ` +
        'Перенесіть або приберіть їх спочатку.',
        'bad',
      )
      return
    }
    if (!confirm(`Видалити категорію «${category.name}»?`)) return
    try {
      await api.categories.remove(category.id)
      notify('Категорію видалено')
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
                          title={c.products_count > 0 ? 'Спочатку приберіть товари' : 'Видалити'}
                        >
                          Видалити
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

export default function Catalog() {
  const notify = useToast()
  const [categories, setCategories] = useState([])
  const [products, setProducts] = useState(null)
  const [filter, setFilter] = useState('')
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [managingCategories, setManagingCategories] = useState(false)

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

  const updateStock = async (product, stock) => {
    try {
      const updated = await api.products.setStock(product.id, Math.max(0, stock))
      setProducts((list) => list.map((p) => (p.id === updated.id ? updated : p)))
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  const hide = async (product) => {
    if (!confirm(`Прибрати «${product.name}» з каталогу? Історія замовлень збережеться.`)) return
    try {
      await api.products.remove(product.id)
      notify('Товар прибрано з каталогу')
      load()
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Каталог</h1>
          <p>Товари, ціни та залишки — усе, що бачить клієнт у боті</p>
        </div>
        <div className="row">
          <button className="btn ghost" onClick={() => setManagingCategories(true)}>Категорії</button>
          <button className="btn" onClick={() => setEditing({})}>Додати товар</button>
        </div>
      </div>

      <div className="toolbar">
        <select className="input" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">Усі категорії</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name} ({c.products_count})</option>
          ))}
        </select>
        <input
          className="input"
          placeholder="Пошук за назвою"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <ErrorBar error={error} />

      {!products ? (
        <Loading />
      ) : products.length === 0 ? (
        <Empty title="Товарів немає">
          Додайте перший товар — він одразу з'явиться в каталозі бота.
        </Empty>
      ) : (
        <div className="card" style={{ padding: '18px 6px' }}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Товар</th>
                  <th>Категорія</th>
                  <th className="num">Ціна</th>
                  <th className="num">Залишок</th>
                  <th>Статус</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {products.map((p) => (
                  <tr key={p.id}>
                    <td>
                      {p.name}
                      {p.description && <div className="faint">{p.description.slice(0, 60)}</div>}
                    </td>
                    <td className="muted">{p.category_name}</td>
                    <td className="num">
                      {money(p.price)}
                      {p.old_price && <div className="faint"><s>{money(p.old_price)}</s></div>}
                    </td>
                    <td className="num">
                      <div className="row" style={{ justifyContent: 'flex-end', gap: 4 }}>
                        <button className="btn ghost small" onClick={() => updateStock(p, p.stock - 1)}>−</button>
                        <span className="mono" style={{ minWidth: 32, textAlign: 'center' }}>{p.stock}</span>
                        <button className="btn ghost small" onClick={() => updateStock(p, p.stock + 1)}>+</button>
                      </div>
                    </td>
                    <td>
                      {!p.is_active ? (
                        <span className="chip">Прихований</span>
                      ) : p.stock === 0 ? (
                        <span className="chip bad">Немає</span>
                      ) : p.stock < 5 ? (
                        <span className="chip warn">Закінчується</span>
                      ) : (
                        <span className="chip ok">В наявності</span>
                      )}
                    </td>
                    <td>
                      <div className="row">
                        <button className="btn ghost small" onClick={() => setEditing(p)}>Змінити</button>
                        {p.is_active && (
                          <button className="btn danger small" onClick={() => hide(p)}>Прибрати</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
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
