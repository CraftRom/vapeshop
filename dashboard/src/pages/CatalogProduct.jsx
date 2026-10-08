import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { api } from '../api'
import { useProductImage } from '../components/catalog/useProductImage'
import { ErrorBar, Field, Info, Loading, money, useToast } from '../components/ui'
import { DescriptionField, DisplayFields, PriceFields, ProductImageField, TaxonomyFields, changeField, groupPayload, pricePayload } from '../components/catalog/ProductFields'

function EditBlock({ title, product, fields, payload, onSaved, children }) {
  const [editing, setEditing] = useState(false), [form, setForm] = useState(product)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const notify = useToast()
  const start = () => { setForm({ ...product }); setError(''); setEditing(true) }
  const save = async (event) => {
    event.preventDefault(); if (busy) return
    setBusy(true); setError('')
    try {
      const changes = payload(form)
      const updated = await api.products.patch(product.id, changes)
      const keys = new Set(Object.keys(changes))
      if (keys.has('category_id') || keys.has('subcategory_id')) {
        keys.add('category_name'); keys.add('subcategory_name')
      }
      if (keys.has('photo_url')) keys.add('has_photo')
      // A slower response from another block must not restore its older snapshot.
      onSaved((current) => current?.id === updated.id ? { ...current, ...Object.fromEntries([...keys].map((key) => [key, updated[key]])) } : current)
      setEditing(false); notify(`${title}: збережено`)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <section className="catalog-edit-block" aria-label={title}><div className="catalog-block-head"><h2>{title}</h2>{!editing && <button className="btn ghost small" onClick={start}>Редагувати</button>}</div>{editing ? <form onSubmit={save}><ErrorBar error={error} /><fieldset disabled={busy}>{fields(form, setForm)}</fieldset><div className="catalog-block-actions"><button className="btn ghost" type="button" disabled={busy} onClick={() => setEditing(false)}>Скасувати</button><button className="btn" disabled={busy}>{busy ? 'Зберігаємо…' : 'Зберегти блок'}</button></div></form> : children}</section>
}
function CurrentImage({ product }) {
  const [image, error] = useProductImage(product)
  return <div className="catalog-detail-image">{image ? <img src={image} alt={product.name} /> : <span className="muted">{error || (product.has_photo ? 'Завантажуємо зображення…' : 'Зображення не додано')}</span>}</div>
}

export default function CatalogProduct() {
  const { id } = useParams(), location = useLocation()
  const [product, setProduct] = useState(null), [categories, setCategories] = useState([]), [subcategories, setSubcategories] = useState([])
  const [error, setError] = useState(''), [retry, setRetry] = useState(0)
  useEffect(() => {
    let alive = true; setError(''); setProduct(null)
    Promise.all([api.products.get(id), api.categories.list(), api.subcategories.list()]).then(([p, c, s]) => { if (alive) { setProduct(p); setCategories(c); setSubcategories(s) } }).catch((err) => alive && setError(err.message))
    return () => { alive = false }
  }, [id, retry])
  const back = location.state?.catalogBack || '/catalog'
  if (error) return <><Link className="btn ghost" to={back}>← Каталог</Link><ErrorBar error={error} /><button className="btn" onClick={() => setRetry((n) => n + 1)}>Повторити</button></>
  if (!product) return <Loading />
  const props = { product, onSaved: setProduct }
  const sub = subcategories.find((s) => s.id === product.subcategory_id)
  return <div className="catalog-product-page">
    <Link className="btn ghost catalog-back-link" to={back}>← До каталогу</Link>
    <div className="page-head"><div><h1>{product.name}</h1><p>Зміни блоків одразу застосовуються до вітрини й бота.</p></div><span className={`chip ${product.is_active ? 'ok' : ''}`}>{product.is_active ? 'Видимий у каталозі' : 'Прихований'}</span></div>
    <div className="catalog-sku-panel"><Info label="Артикул (SKU)" copy={product.sku}><strong className="mono">{product.sku}</strong></Info><span className="muted">Автоматично створений · незмінний</span></div>
    <div className="catalog-detail-grid">
      <EditBlock {...props} title="Основне та відображення" payload={(f) => ({ name: f.name.trim(), stock: Number(f.stock), sort_order: Number(f.sort_order), is_active: f.is_active, is_new: f.is_new })} fields={(f, set) => <><Field label="Назва товару"><input className="input" aria-label="Назва товару" required maxLength={255} value={f.name} onChange={changeField(set, 'name')} /></Field><DisplayFields form={f} setForm={set} /></>}><p>{product.is_new ? 'Новинка · показується в розділі «Новинки»' : 'Звичайний товар'}</p><p>Залишок: <strong>{product.stock} шт.</strong> · Порядок: {product.sort_order}</p></EditBlock>
      <EditBlock {...props} title="Категорія та субкатегорія" payload={groupPayload} fields={(f, set) => <TaxonomyFields form={f} setForm={set} categories={categories} subcategories={subcategories} />}><p>Категорія: <strong>{product.category_name || 'Не призначена'}</strong></p><p>Субкатегорія: <strong>{product.subcategory_name || 'Не призначена'}</strong></p>{!product.category_id && sub?.category_name && <p className="muted">Батьківська категорія субкатегорії: {sub.category_name}</p>}</EditBlock>
      <EditBlock {...props} title="Ціни та акція" payload={pricePayload} fields={(f, set) => <PriceFields form={f} setForm={set} />}><p className="catalog-detail-price">{money(product.price)} {product.is_sale && <s>{money(product.old_price)}</s>}</p><p>{product.is_sale ? 'Акція · знижка відображається в каталозі' : 'Акція вимкнена'}</p></EditBlock>
      <EditBlock {...props} title="Зображення" payload={(f) => ({ photo_url: f.photo_url || null })} fields={(f, set) => <><ProductImageField form={f} setForm={set} />{product.has_photo && !f.photo_url && <p className="muted">Збереження порожнього зображення прибере поточне фото.</p>}</>}><CurrentImage product={product} /></EditBlock>
      <div className="catalog-description-block"><EditBlock {...props} title="Опис" payload={(f) => ({ description: f.description || null })} fields={(f, set) => <DescriptionField form={f} setForm={set} />}><p className="catalog-detail-description">{product.description || 'Опис не додано'}</p></EditBlock></div>
    </div>
  </div>
}
