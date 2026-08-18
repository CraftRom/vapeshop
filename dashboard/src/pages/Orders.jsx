import { useCallback, useEffect, useState } from 'react'

import { api } from '../api'
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
              {order.items.map((item) => (
                <tr key={item.id}>
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
  const notify = useToast()
  const [orders, setOrders] = useState(null)
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)

  const load = useCallback(async () => {
    setError('')
    try {
      setOrders(await api.orders.list({ status, search }))
    } catch (err) {
      setError(err.message)
    }
  }, [status, search])

  useEffect(() => {
    const timer = setTimeout(load, search ? 350 : 0)
    return () => clearTimeout(timer)
  }, [load, search])

  const changeStatus = async (order, next) => {
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
        <div className="spacer" />
        <button className="btn ghost small" onClick={load}>Оновити</button>
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
                      <span className="id-tag">#{order.id}</span>
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
                      <StatusRail status={order.status} onChange={(next) => changeStatus(order, next)} />
                    </td>
                    <td>
                      <button className="btn ghost small" onClick={() => setSelected(order)}>
                        Деталі
                      </button>
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
