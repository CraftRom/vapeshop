import { useEffect, useId, useRef, useState } from 'react'

import { api } from '../api'
import { Empty, ErrorBar, Field, Loading, Modal, confirmPurge, useToast } from '../components/ui'

// Значення мають збігатися з OperatorRole на бекенді. «admin» історично
// означає системного адміністратора з .env — його в панелі не створюють,
// тому в списку вибору його немає, а в таблиці підпис потрібен.
const ROLE_LABEL = {
  admin: 'Системний адміністратор',
  shop_admin: 'Адміністратор',
  operator: 'Менеджер',
}

// Ролі, які можна призначити з панелі.
const CREATABLE_ROLES = [
  { value: 'operator', label: 'Менеджер',
    hint: 'Працює із замовленнями й клієнтами' },
  { value: 'shop_admin', label: 'Адміністратор',
    hint: 'Додатково змінює платіжні реквізити й керує обліковими записами' },
]

const MIN_PASSWORD_LENGTH = 12
const MAX_PASSWORD_LENGTH = 128
const characterCount = (value) => [...value].length

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
  const [touched, setTouched] = useState({})
  const saving = useRef(false)
  const formId = useId()

  const loginValid = editing || /^[A-Za-z0-9_.-]{3,64}$/.test(form.login.trim())
  const passwordLength = characterCount(form.password)
  const passwordValid = (editing && form.password === '') ||
    (passwordLength >= MIN_PASSWORD_LENGTH && passwordLength <= MAX_PASSWORD_LENGTH)
  const nameProblem = characterCount(form.name.trim()) > 128
    ? 'Ім’я має містити не більше 128 символів.'
    : form.name.includes('\0') ? 'Приберіть неприпустимий символ з імені.' : ''
  const nameValid = !nameProblem
  const canSave = loginValid && passwordValid && nameValid
  const touch = (field) => () => setTouched((old) => ({ ...old, [field]: true }))
  const close = () => { if (!saving.current) onClose() }

  const set = (key) => (e) => {
    setForm((f) => ({ ...f, [key]: e.target.value }))
    setError('')
  }

  const save = async () => {
    if (saving.current || !canSave) return
    saving.current = true
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
        notify('Обліковий запис створено')
      }
      onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  return (
    <Modal
      title={editing ? `Обліковий запис «${operator.login}»` : 'Новий обліковий запис'}
      onClose={close}
      footer={
        <>
          <button className="btn ghost" onClick={close} disabled={busy}>Скасувати</button>
          <button className="btn" onClick={save} disabled={!canSave || busy}>
            {busy ? 'Збереження…' : editing ? 'Зберегти' : 'Створити'}
          </button>
        </>
      }
    >
      <ErrorBar error={error} />

      {!editing && (
        <Field label="Логін" htmlFor={`${formId}-login`} hint={<span id={`${formId}-login-hint`}>
          {touched.login && !loginValid
            ? 'Введіть від 3 до 64 символів: латиниця, цифри, крапка, дефіс або підкреслення.'
            : 'Від 3 до 64 символів: латиниця, цифри, крапка, дефіс або підкреслення. Змінити пізніше не можна.'}
        </span>}>
          <input id={`${formId}-login`} className="input" value={form.login} onChange={set('login')}
            onBlur={touch('login')} aria-invalid={Boolean(touched.login && !loginValid)} aria-describedby={`${formId}-login-hint`} disabled={busy} autoFocus />
        </Field>
      )}

      <Field label="Імʼя" htmlFor={`${formId}-name`} hint={<span id={`${formId}-name-hint`}>
        {touched.name && nameProblem
          ? nameProblem
          : 'Показується в панелі. До 128 символів; можна залишити порожнім.'}
      </span>}>
        <input id={`${formId}-name`} className="input" value={form.name} onChange={set('name')} onBlur={touch('name')}
          aria-invalid={Boolean(touched.name && !nameValid)} aria-describedby={`${formId}-name-hint`} disabled={busy} />
      </Field>

      <Field
        label={editing ? 'Новий пароль' : 'Пароль'}
        htmlFor={`${formId}-password`}
        hint={<span id={`${formId}-password-hint`}>
          {touched.password && !passwordValid
            ? 'Мінімум 12 символів, максимум 128. Пробіли й спецсимволи дозволені.'
            : editing
              ? 'Лишіть порожнім, щоб не змінювати. Мінімум 12 символів, максимум 128.'
              : 'Мінімум 12 символів, максимум 128. Не лише цифри.'}
        </span>}
      >
        <input
          className="input"
          id={`${formId}-password`}
          type="password"
          value={form.password}
          onChange={set('password')}
          onBlur={touch('password')}
          aria-invalid={Boolean(touched.password && !passwordValid)}
          aria-describedby={`${formId}-password-hint`}
          disabled={busy}
          autoComplete="new-password"
        />
      </Field>

      <Field
        label="Роль"
        htmlFor={`${formId}-role`}
        hint={
          (CREATABLE_ROLES.find((r) => r.value === form.role) || {}).hint +
          '. Налаштування бота, розсилок і бекапів лишаються за системним ' +
          'адміністратором — його обліковий запис задається у файлі .env'
        }
      >
        <select id={`${formId}-role`} className="input" value={form.role} onChange={set('role')} disabled={busy}>
          {CREATABLE_ROLES.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
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
          розсилками. З налаштувань йому доступні бонуси, реферальна програма
          та знижка від суми. Реквізити оплати, адреси й список менеджерів
          лишаються за адміністратором.
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
