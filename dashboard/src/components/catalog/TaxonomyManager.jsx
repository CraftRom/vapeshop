import { useState } from 'react'
import { api } from '../../api'
import { ErrorBar, Field, Modal, confirmPurge, useToast } from '../ui'

function GroupForm({ group, kind, categories, onClose, onSaved }) {
  const [form, setForm] = useState({ name: '', description: '', category_id: '', sort_order: 0, is_active: true, ...group })
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const client = kind === 'sub' ? api.subcategories : api.categories
  const set = (key) => (event) => setForm((old) => ({ ...old, [key]: event.target.type === 'checkbox' ? event.target.checked : event.target.value }))
  const save = async (event) => {
    event.preventDefault(); if (busy) return
    setBusy(true); setError('')
    const payload = { name: form.name.trim(), description: form.description || null, sort_order: Number(form.sort_order), is_active: form.is_active }
    if (kind === 'sub') payload.category_id = form.category_id ? Number(form.category_id) : null
    try { await (group?.id ? client.update(group.id, payload) : client.create(payload)); await onSaved(); onClose() }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const title = `${group?.id ? 'Редагувати' : 'Нова'} ${kind === 'sub' ? 'субкатегорія' : 'категорія'}`
  return <Modal title={title} onClose={() => !busy && onClose()} footer={<><button className="btn ghost" onClick={onClose} disabled={busy}>Скасувати</button><button className="btn" type="submit" form="catalog-group-form" disabled={busy || !form.name.trim()}>Зберегти</button></>}><form id="catalog-group-form" onSubmit={save} className="stack"><ErrorBar error={error} /><Field label="Назва"><input className="input" aria-label="Назва групи" maxLength={128} required autoFocus value={form.name} onChange={set('name')} /></Field>{kind === 'sub' && <Field label="Батьківська категорія" hint="При переміщенні субкатегорії категорія її товарів узгоджується автоматично"><select className="input" aria-label="Батьківська категорія" value={form.category_id ?? ''} onChange={set('category_id')}><option value="">Без батьківської категорії</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>}<Field label="Опис"><textarea className="input" aria-label="Опис групи" value={form.description || ''} onChange={set('description')} /></Field><Field label="Порядок"><input className="input" aria-label="Порядок групи" type="number" value={form.sort_order} onChange={set('sort_order')} /></Field><label className="catalog-check"><input type="checkbox" checked={form.is_active} onChange={set('is_active')} />Показувати групу в каталозі</label></form></Modal>
}
export default function TaxonomyManager({ categories, subcategories, onClose, onChanged }) {
  const [editing, setEditing] = useState(null), [busy, setBusy] = useState('')
  const notify = useToast()
  const remove = async (group, kind, purge) => {
    const label = kind === 'sub' ? 'Субкатегорія' : 'Категорія'
    const warning = `Пов’язані товари: ${group.products_count}. ${purge ? 'Вони будуть видалені назавжди.' : 'Вони будуть приховані.'} Історія замовлень збережеться.`
    if (!(purge ? confirmPurge(group.name, warning) : confirm(`${label} «${group.name}»: приховати? ${warning}`))) return
    setBusy(`${kind}:${group.id}`)
    try { await (kind === 'sub' ? api.subcategories : api.categories)[purge ? 'purge' : 'remove'](group.id); await onChanged(); notify(purge ? 'Групу видалено' : 'Групу приховано') }
    catch (err) { notify(err.message, 'bad') } finally { setBusy('') }
  }
  const section = (title, rows, kind) => <section className="catalog-form-section"><div className="catalog-block-head"><h3>{title}</h3><button className="btn small" onClick={() => setEditing({ kind, group: null })}>{kind === 'sub' ? 'Нова субкатегорія' : 'Нова категорія'}</button></div>{!rows.length && <p className="muted">Поки немає. Товари можуть існувати без груп.</p>}<div className="taxonomy-list">{rows.map((group) => <article className="taxonomy-row" key={group.id}><div><strong>{group.name}</strong><div className="muted">{kind === 'sub' && `${group.category_name || 'Без батьківської категорії'} · `}{group.products_count} товарів · {group.is_active ? 'Активна' : 'Прихована'}</div></div><div className="row"><button className="btn ghost small" onClick={() => setEditing({ kind, group })}>Змінити</button><button className="btn ghost small" disabled={Boolean(busy)} onClick={() => remove(group, kind, false)}>Приховати</button><button className="btn danger small" disabled={Boolean(busy)} onClick={() => remove(group, kind, true)}>Стерти</button></div></article>)}</div></section>
  return <><Modal title="Категорії та субкатегорії" onClose={onClose} footer={<button className="btn ghost" onClick={onClose}>Закрити</button>}><div className="taxonomy-manager"><p className="muted">Категорії об’єднують субкатегорії. Субкатегорії й товари можуть існувати самостійно.</p>{section('Категорії', categories, 'root')}{section('Субкатегорії', subcategories, 'sub')}</div></Modal>{editing && <GroupForm group={editing.group} kind={editing.kind} categories={categories} onClose={() => setEditing(null)} onSaved={onChanged} />}</>
}
