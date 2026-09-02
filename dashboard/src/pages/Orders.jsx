import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api, isSysadmin } from '../api'
import StatusRail, { STATUS_LABELS } from '../components/StatusRail'
import { Empty, ErrorBar, Field, Loading, Modal, dateTime, money, useToast } from '../components/ui'

const FILTERS = [
  { value: '', label: 'Усі' },
  { value: 'new', label: 'Нові' },
  { value: 'confirmed', label: 'Підтверджені' },
  { value: 'paid', label: 'Оплачені' },
  { value: 'shipped', label: 'Відправлені' },
  { value: 'done', label: 'Виконані' },
  { value: 'cancelled', label: 'Скасовані' },
]

function OrderDetails({ order, onClose, onSaved }) {
  const notify = useToast()
  const [note, setNote] = useState(order.admin_note || '')
  const [busy, setBusy] = useState(false)

  const saveNote = async () => {
    setBusy(true)
    try {
      const updated = await api.orders.patch(order.id, { admin_note: note })
      onSaved(updated)
      notify('Нотатку збережено')
      onClose()
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  const customer = order.user
  const contact = customer?.username ? `@${customer.username}` : `id${customer?.tg_id ?? '—'}`

  return (
    <Modal
      title={`Замовлення №${order.id}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Закрити</button>
          <button className="btn" onClick={saveNote} disabled={busy}>Зберегти нотатку</button>
        </>
      }
    >
      <div className="stack">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Товар</th>
                <th className="num">Шт</th>
                <th className="num">Сума</th>
              </tr>
            </thead>
            <tbody>
              {order.items.map((item, index) => (
                <tr key={item.id ?? index}>
                  <td>{item.name}</td>
                  <td className="num">{item.qty}</td>
                  <td className="num">{money(item.price * item.qty)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card" style={{ background: 'var(--panel-2)' }}>
          <div className="row"><span style={{ flex: 1 }} className="muted">Сума</span><span className="mono">{money(order.subtotal)}</span></div>
          {Number(order.discount) > 0 && (
            <div className="row"><span style={{ flex: 1 }} className="muted">Промокод</span><span className="mono">−{money(order.discount)}</span></div>
          )}
          {Number(order.bonus_used) > 0 && (
            <div className="row"><span style={{ flex: 1 }} className="muted">Бонуси</span><span className="mono">−{money(order.bonus_used)}</span></div>
          )}
          <div className="row" style={{ marginTop: 6 }}>
            <strong style={{ flex: 1 }}>До сплати</strong>
            <strong className="mono">{money(order.total)}</strong>
          </div>
        </div>

        <div>
          <h3>Клієнт і доставка</h3>
          <p className="muted" style={{ margin: '8px 0 0' }}>
            {order.contact_name} · <span className="mono">{order.contact_phone}</span> · {contact}<br />
            {order.delivery_city}, {order.delivery_address}<br />
            Оплата: {order.payment_method === 'card' ? 'переказ на картку' : 'накладений платіж'}<br />
            Створено: {dateTime(order.created_at)}
          </p>
          {order.comment && <p style={{ marginBottom: 0 }}>Коментар клієнта: {order.comment}</p>}
        </div>

        <Field label="Нотатка менеджера" hint="Видно лише в панелі, клієнт її не бачить">
          <textarea className="input" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  )
}

export default function Orders() {
  const navigate = useNavigate()
  const notify = useToast()
  const [orders, setOrders] = useState(null)
  const [status, setStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)
  // Клієнт відповідає в боті, тож панель має сама помічати нові повідомлення
  const [unread, setUnread] = useState({})

  /** Видалення замовлення. Тільки системний адміністратор.
   *
   *  Менеджерам цього не дають навмисно: замовлення — первинний документ.
   *  Помилкове скасовують статусом, так лишається слід. Стирати доводиться
   *  хіба що тестові записи після налаштування.
   */
  const removeOrder = async (order) => {
    if (!window.confirm(
      `Стерти замовлення №${order.id} на ${money(order.total)}? ` +
      'Відновити можна буде лише з резервної копії.',
    )) return
    try {
      await api.ordersAdmin.remove(order.id)
      notify(`Замовлення №${order.id} стерто`)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const purgeAll = async () => {
    // Два питання поспіль, і друге — з переписуванням. Дія стирає ще й
    // підсумки клієнтів, і повернути це можна лише з копії.
    if (!window.confirm('Стерти ВСІ замовлення разом із підсумками клієнтів?')) return
    const typed = window.prompt('Це незворотно. Введіть DELETE ALL для підтвердження:')
    if (typed !== 'DELETE ALL') {
      if (typed !== null) setError('Підтвердження не збіглося — нічого не стерто')
      return
    }
    try {
      const result = await api.ordersAdmin.purge()
      notify(`Стерто замовлень: ${result.removed}`)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const load = useCallback(async () => {
    setError('')
    try {
      setOrders(await api.orders.list({
        status, search,
        // Порожнє поле не надсилаємо: бекенд перевіряє формат дати
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      }))
    } catch (err) {
      setError(err.message)
    }
  }, [status, search, dateFrom, dateTo])

  useEffect(() => {
    const timer = setTimeout(load, search ? 350 : 0)
    return () => clearTimeout(timer)
  }, [load, search])

  // Клієнт відповідає в боті, а не в панелі — тож лічильник опитуємо самі
  useEffect(() => {
    const poll = () => {
      if (document.hidden) return
      api.orders.unread().then(setUnread).catch(() => {})
    }
    poll()
    const timer = setInterval(poll, 20000)
    document.addEventListener('visibilitychange', poll)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', poll)
    }
  }, [])

  const changeStatus = async (order, next) => {
    // Відправлення потребує накладної, а вікно для неї — на сторінці
    // замовлення. Без цього менеджер тиснув би тут і отримував відмову.
    if (next === 'shipped') {
      navigate(`/orders/${order.id}?ship=1`)
      return
    }
    const previous = orders
    setOrders((list) => list.map((o) => (o.id === order.id ? { ...o, status: next } : o)))
    try {
      await api.orders.patch(order.id, { status: next })
      notify(`Замовлення №${order.id}: ${STATUS_LABELS[next]}`)
    } catch (err) {
      setOrders(previous)
      notify(err.message, 'bad')
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Замовлення</h1>
          <p>Клік по етапу переводить замовлення далі — клієнт одразу отримає сповіщення</p>
        </div>
      </div>

      <div className="toolbar">
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          {FILTERS.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
        <input
          className="input"
          placeholder="Ім'я або телефон"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <input
          className="input"
          type="date"
          value={dateFrom}
          max={dateTo || undefined}
          onChange={(e) => setDateFrom(e.target.value)}
          title="Від дати"
          style={{ maxWidth: 160 }}
        />
        <input
          className="input"
          type="date"
          value={dateTo}
          min={dateFrom || undefined}
          onChange={(e) => setDateTo(e.target.value)}
          title="По дату включно"
          style={{ maxWidth: 160 }}
        />
        {(dateFrom || dateTo) && (
          <button
            className="btn ghost small"
            onClick={() => { setDateFrom(''); setDateTo('') }}
          >
            Скинути дати
          </button>
        )}
        <div className="spacer" />
        <button className="btn ghost small" onClick={load}>Оновити</button>
        {isSysadmin() && (
          <button className="btn danger small" onClick={purgeAll}>
            Стерти всі
          </button>
        )}
      </div>

      <ErrorBar error={error} />

      {!orders ? (
        <Loading />
      ) : orders.length === 0 ? (
        <Empty title="Замовлень немає">
          Щойно клієнт оформить замовлення в боті, воно з'явиться тут.
        </Empty>
      ) : (
        <div className="card" style={{ padding: '18px 6px' }}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>№</th>
                  <th>Клієнт</th>
                  <th>Склад</th>
                  <th className="num">Сума</th>
                  <th style={{ minWidth: 300 }}>Статус</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr key={order.id}>
                    <td>
                      <Link to={`/orders/${order.id}`} className="id-tag">#{order.id}</Link>
                      {unread[order.id] > 0 && (
                        <span
                          className="chip"
                          style={{ marginLeft: 6 }}
                          title="Непрочитані повідомлення від клієнта"
                        >
                          💬 {unread[order.id]}
                        </span>
                      )}
                      <div className="faint">{dateTime(order.created_at)}</div>
                    </td>
                    <td>
                      {order.contact_name}
                      <div className="faint mono">{order.contact_phone}</div>
                    </td>
                    <td className="faint" style={{ maxWidth: 220 }}>
                      {order.items.map((i) => `${i.name} ×${i.qty}`).join(', ')}
                    </td>
                    <td className="num">{money(order.total)}</td>
                    <td>
                      <StatusRail
                        status={order.status}
                        paymentMethod={order.payment_method}
                        onChange={(next) => changeStatus(order, next)}
                      />
                    </td>
                    <td>
                      <div className="row">
                        <Link className="btn ghost small" to={`/orders/${order.id}`}>
                          Відкрити
                        </Link>
                        <button className="btn ghost small" onClick={() => setSelected(order)}>
                          Швидкий перегляд
                        </button>
                        {isSysadmin() && (
                          <button
                            className="btn danger small"
                            onClick={() => removeOrder(order)}
                          >
                            Стерти
                          </button>
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

      {selected && (
        <OrderDetails
          order={selected}
          onClose={() => setSelected(null)}
          onSaved={(updated) =>
            setOrders((list) => list.map((o) => (o.id === updated.id ? updated : o)))
          }
        />
      )}
    </>
  )
}
