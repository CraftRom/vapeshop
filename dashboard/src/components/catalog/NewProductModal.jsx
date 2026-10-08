import { useState } from 'react'
import { api } from '../../api'
import { ErrorBar, Field, Modal, useToast } from '../ui'
import { DescriptionField, DisplayFields, PriceFields, ProductImageField, TaxonomyFields, changeField, emptyProduct, groupPayload, pricePayload, validateProduct } from './ProductFields'

export default function NewProductModal({ categories, subcategories, onClose, onSaved }) {
  const [form, setForm] = useState({ ...emptyProduct })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const notify = useToast()
  const save = async (event) => {
    event.preventDefault()
    if (busy) return
    const problem = validateProduct(form)
    if (problem) { setError(problem); return }
    setBusy(true); setError('')
    try {
      const product = await api.products.create({ ...form, name: form.name.trim(), ...groupPayload(form), ...pricePayload(form), stock: Number(form.stock), sort_order: Number(form.sort_order), description: form.description || null, photo_url: form.photo_url || null })
      onSaved(product); notify(`Товар створено · ${product.sku}`); onClose()
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }
  return <Modal title="Новий товар" onClose={() => !busy && onClose()} footer={<><button className="btn ghost" disabled={busy} onClick={onClose}>Скасувати</button><button className="btn" type="submit" form="new-product-form" disabled={busy}>{busy ? 'Створюємо…' : 'Створити товар'}</button></>}>
    <form id="new-product-form" className="catalog-new-form" onSubmit={save}>
      <ErrorBar error={error} />
      <fieldset disabled={busy}>
        <section className="catalog-form-section"><h3>Основне</h3><Field label="Назва товару"><input className="input" aria-label="Назва товару" required maxLength={255} autoFocus value={form.name} onChange={changeField(setForm, 'name')} /></Field><div className="catalog-sku-note"><strong>Артикул (SKU) · автоматично</strong><span>Унікальний артикул з’явиться після створення. Він зберігається при всіх подальших змінах.</span></div></section>
        <section className="catalog-form-section"><h3>Категорія та субкатегорія</h3><TaxonomyFields form={form} setForm={setForm} categories={categories} subcategories={subcategories} /></section>
        <section className="catalog-form-section"><h3>Ціни</h3><PriceFields form={form} setForm={setForm} /></section>
        <section className="catalog-form-section"><h3>Опис і зображення</h3><DescriptionField form={form} setForm={setForm} /><ProductImageField form={form} setForm={setForm} /></section>
        <section className="catalog-form-section"><h3>Відображення та склад</h3><DisplayFields form={form} setForm={setForm} /></section>
      </fieldset>
    </form>
  </Modal>
}
