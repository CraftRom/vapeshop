import { useEffect, useState } from 'react'

import { api } from '../api'
import { Empty, ErrorBar, Field, Loading, Modal, confirmPurge, useToast } from '../components/ui'

const ROLE_LABEL = { admin: 'Адміністратор', operator: 'Менеджер' }

function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('uk-UA', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function OperatorForm({ operator, onClose, onSaved }) {
  const notify = useToast()
  const editing = Boolean(operator?.id)
  const [form, setForm] = useState({
    login: operator?.login || '',
    name: operator?.name || '',
    password: '',
    role: operator?.role || 'operator',
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      if (editing) {
        const payload = { name: form.name.trim(), role: form.role }
        // Порожнє поле означає «пароль не змінюємо»
        if (form.password) payload.password = form.password
        await api.operators.update(operator.id, payload)
        notify('Дані оновлено')
      } else {
        await api.operators.create({
          login: form.login.trim(),
          name: form.name.trim(),
          password: form.password,
          role: form.role,
        })
        notify('Менеджера створено')
      }
      onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const canSave = editing
    ? form.name.trim().length > 0 || form.password.length >= 8
    : form.login.trim().length >= 3 && form.password.length >= 8

  return (
    <Modal
      title={editing ? `Обліковий запис «${operator.login}»` : 'Новий менеджер'}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Скасувати</button>
          <button className="btn" onClick={save} disabled={!canSave || busy}>
            {busy ? 'Збереження…' : editing ? 'Зберегти' : 'Створити'}
          </button>
        </>
      }
    >
      <ErrorBar error={error} />

      {!editing && (
        <Field label="Логін" hint="Латиниця, цифри, крапка, дефіс. Змінити пізніше не можна">
          <input className="input" value={form.login} onChange={set('login')} autoFocus />
        </Field>
      )}

      <Field label="Імʼя" hint="Показується в панелі, щоб було видно, хто на зміні">
        <input className="input" value={form.name} onChange={set('name')} />
      </Field>

      <Field
        label={editing ? 'Новий пароль' : 'Пароль'}
        hint={editing
          ? 'Лишіть порожнім, щоб не змінювати. Мінімум 8 символів'
          : 'Мінімум 8 символів, не лише цифри'}
      >
        <input
          className="input"
          type="password"
          value={form.password}
          onChange={set('password')}
          autoComplete="new-password"
        />
      </Field>

      <Field label="Роль" hint="Адміністратор додатково керує менеджерами й усіма налаштуваннями">
        <select className="input" value={form.role} onChange={set('role')}>
          <option value="operator">Менеджер</option>
          <option value="admin">Адміністратор</option>
        </select>
      </Field>
    </Modal>
  )
}

export default function Operators() {
  const notify = useToast()
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)

  const load = () => {
    api.operators
      .list()
      .then(setRows)
      .catch((err) => setError(err.message))
  }

  useEffect(load, [])

  const toggle = async (operator) => {
    try {
      if (operator.is_active) {
        await api.operators.remove(operator.id)
        notify('Доступ вимкнено')
      } else {
        await api.operators.update(operator.id, { is_active: true })
        notify('Доступ повернено')
      }
      load()
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  const purge = async (operator) => {
    if (!confirmPurge(operator.login, 'Обліковий запис зникне назавжди.')) return
    try {
      await api.operators.purge(operator.id)
      notify('Обліковий запис стерто')
      load()
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  if (error && !rows) return <ErrorBar error={error} />
  if (!rows) return <Loading />

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Менеджери</h1>
          <p>Хто має доступ до панелі й на якому рівні</p>
        </div>
        <button className="btn" onClick={() => setEditing({})}>Новий менеджер</button>
      </div>

      <ErrorBar error={error} />

      <div className="card" style={{ marginBottom: 18 }}>
        <p className="faint" style={{ margin: 0 }}>
          Менеджер працює із замовленнями, каталогом, клієнтами, промокодами та
          розсилками. З налаштувань йому доступна лише реферальна програма —
          реквізити оплати, адреси й список менеджерів лишаються за адміністратором.
        </p>
      </div>

      {rows.length === 0 ? (
        <Empty title="Менеджерів ще немає">
          Поки що в панель заходить лише адміністратор із налаштувань сервера.
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Логін</th>
                <th>Імʼя</th>
                <th>Роль</th>
                <th>Останній вхід</th>
                <th>Статус</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => (
                <tr key={o.id} style={{ opacity: o.is_active ? 1 : 0.55 }}>
                  <td>{o.login}</td>
                  <td>{o.name || '—'}</td>
                  <td>{ROLE_LABEL[o.role] || o.role}</td>
                  <td className="faint">{formatDate(o.last_login_at)}</td>
                  <td>
                    <span className={`chip ${o.is_active ? 'ok' : ''}`}>
                      {o.is_active ? 'Активний' : 'Вимкнений'}
                    </span>
                  </td>
                  <td>
                    <div className="row">
                      <button className="btn small ghost" onClick={() => setEditing(o)}>
                        Змінити
                      </button>
                      <button
                        className={o.is_active ? 'btn danger small' : 'btn small ghost'}
                        onClick={() => toggle(o)}
                        title="Доступ закривається, історія дій лишається"
                      >
                        {o.is_active ? 'Вимкнути' : 'Увімкнути'}
                      </button>
                      <button
                        className="btn danger small"
                        onClick={() => purge(o)}
                        title="Стерти запис назавжди. Імʼя в замовленнях збережеться"
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

      {editing && (
        <OperatorForm
          operator={editing.id ? editing : null}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </>
  )
}
