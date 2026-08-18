import { useCallback, useEffect, useState } from 'react'

import { api } from '../api'
import { Empty, ErrorBar, Field, Loading, Modal, date, money, useToast } from '../components/ui'

const EMPTY = {
  code: '',
  type: 'percent',
  value: '',
  min_order: 0,
  max_uses: '',
  per_user_limit: 1,
  expires_at: '',
  is_active: true,
}

function PromoForm({ promo, onClose, onSaved }) {
  const notify = useToast()
  const [form, setForm] = useState({
    ...EMPTY,
    ...promo,
    expires_at: promo?.expires_at ? promo.expires_at.slice(0, 10) : '',
    max_uses: promo?.max_uses ?? '',
  })
  const [error, setError] = useState('')

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }

  const save = async () => {
    setError('')
    const payload = {
      code: form.code.trim().toUpperCase(),
      type: form.type,
      value: Number(form.value),
      min_order: Number(form.min_order || 0),
      max_uses: form.max_uses === '' ? null : Number(form.max_uses),
      per_user_limit: Number(form.per_user_limit || 1),
      expires_at: form.expires_at ? new Date(`${form.expires_at}T23:59:59`).toISOString() : null,
      is_active: form.is_active,
    }
    try {
      promo?.id ? await api.promos.update(promo.id, payload) : await api.promos.create(payload)
      notify(promo?.id ? 'Промокод оновлено' : 'Промокод створено')
      onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <Modal
      title={promo?.id ? 'Редагувати промокод' : 'Новий промокод'}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Скасувати</button>
          <button className="btn" onClick={save} disabled={!form.code.trim() || !(Number(form.value) > 0)}>
            Зберегти
          </button>
        </>
      }
    >
      <div className="stack">
        <ErrorBar error={error} />
        <div className="grid k2">
          <Field label="Код" hint="Клієнт вводить його при оформленні">
            <input
              className="input mono"
              value={form.code}
              onChange={(e) => setForm((f) => ({ ...f, code: e.target.value.toUpperCase() }))}
              autoFocus
            />
          </Field>
          <Field label="Тип знижки">
            <select className="input" value={form.type} onChange={set('type')}>
              <option value="percent">Відсоток</option>
              <option value="fixed">Фіксована сума</option>
            </select>
          </Field>
        </div>
        <div className="grid k2">
          <Field label={form.type === 'percent' ? 'Знижка, %' : 'Знижка, ₴'}>
            <input className="input" type="number" min="0" value={form.value} onChange={set('value')} />
          </Field>
          <Field label="Мінімальна сума замовлення, ₴">
            <input className="input" type="number" min="0" value={form.min_order} onChange={set('min_order')} />
          </Field>
        </div>
        <div className="grid k3">
          <Field label="Ліміт використань" hint="Порожньо — без ліміту">
            <input className="input" type="number" min="1" value={form.max_uses} onChange={set('max_uses')} />
          </Field>
          <Field label="На одного клієнта">
            <input className="input" type="number" min="1" value={form.per_user_limit} onChange={set('per_user_limit')} />
          </Field>
          <Field label="Діє до">
            <input className="input" type="date" value={form.expires_at} onChange={set('expires_at')} />
          </Field>
        </div>
        <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
          <input type="checkbox" checked={form.is_active} onChange={set('is_active')} />
          Промокод активний
        </label>
      </div>
    </Modal>
  )
}

export default function Promos() {
  const notify = useToast()
  const [promos, setPromos] = useState(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)

  const load = useCallback(async () => {
    setError('')
    try {
      setPromos(await api.promos.list())
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const deactivate = async (promo) => {
    if (!confirm(`Вимкнути промокод ${promo.code}?`)) return
    try {
      await api.promos.remove(promo.id)
      notify('Промокод вимкнено')
      load()
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  const isExpired = (p) => p.expires_at && new Date(p.expires_at) < new Date()
  const isExhausted = (p) => p.max_uses !== null && p.used_count >= p.max_uses

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Промокоди</h1>
          <p>Знижки, які клієнт вводить при оформленні замовлення</p>
        </div>
        <button className="btn" onClick={() => setEditing({})}>Створити промокод</button>
      </div>

      <ErrorBar error={error} />

      {!promos ? (
        <Loading />
      ) : promos.length === 0 ? (
        <Empty title="Промокодів немає">
          Створіть перший код — наприклад, вітальні 10% для нових клієнтів.
        </Empty>
      ) : (
        <div className="card" style={{ padding: '18px 6px' }}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Код</th>
                  <th>Знижка</th>
                  <th className="num">Від суми</th>
                  <th className="num">Використано</th>
                  <th>Діє до</th>
                  <th>Статус</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {promos.map((p) => (
                  <tr key={p.id}>
                    <td className="id-tag">{p.code}</td>
                    <td>{p.type === 'percent' ? `${Number(p.value)}%` : money(p.value)}</td>
                    <td className="num">{Number(p.min_order) > 0 ? money(p.min_order) : '—'}</td>
                    <td className="num">
                      {p.used_count}
                      {p.max_uses !== null && <span className="faint"> / {p.max_uses}</span>}
                    </td>
                    <td className="faint">{p.expires_at ? date(p.expires_at) : 'безстроково'}</td>
                    <td>
                      {!p.is_active ? (
                        <span className="chip">Вимкнений</span>
                      ) : isExpired(p) ? (
                        <span className="chip bad">Прострочений</span>
                      ) : isExhausted(p) ? (
                        <span className="chip warn">Вичерпаний</span>
                      ) : (
                        <span className="chip ok">Активний</span>
                      )}
                    </td>
                    <td>
                      <div className="row">
                        <button className="btn ghost small" onClick={() => setEditing(p)}>Змінити</button>
                        {p.is_active && (
                          <button className="btn danger small" onClick={() => deactivate(p)}>Вимкнути</button>
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
        <PromoForm
          promo={editing.id ? editing : null}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </>
  )
}
