import { useCallback, useEffect, useState } from 'react'

import { api } from '../api'
import { STATUS_LABELS } from '../components/StatusRail'
import { Empty, ErrorBar, Field, Loading, Modal, date, money, useToast } from '../components/ui'

function BonusForm({ customer, onClose, onSaved }) {
  const notify = useToast()
  const [amount, setAmount] = useState('')
  const [error, setError] = useState('')

  const save = async () => {
    try {
      const updated = await api.customers.patch(customer.id, {
        bonus_delta: Number(amount),
        bonus_reason: 'manual',
      })
      onSaved(updated)
      notify('Бонусний баланс змінено')
      onClose()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <Modal
      title="Змінити бонуси"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Скасувати</button>
          <button className="btn" onClick={save} disabled={!amount || Number(amount) === 0}>
            Застосувати
          </button>
        </>
      }
    >
      <div className="stack">
        <ErrorBar error={error} />
        <p className="muted" style={{ margin: 0 }}>
          Поточний баланс: <span className="mono">{money(customer.bonus_balance)}</span>
        </p>
        <Field label="Сума" hint="Додатне число нараховує бонуси, від'ємне — списує">
          <input
            className="input"
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            autoFocus
          />
        </Field>
      </div>
    </Modal>
  )
}

function CustomerOrders({ customer, onClose }) {
  const [orders, setOrders] = useState(null)
  const [saved, setSaved] = useState(null)

  useEffect(() => {
    api.customers.orders(customer.id).then(setOrders).catch(() => setOrders([]))
    // Відкладене вантажимо поруч із замовленнями: менеджер відкриває
    // картку клієнта саме тоді, коли з ним говорить, і питання «те, що я
    // відкладав» приходить у тій самій розмові.
    api.customers.wishlists(customer.id).then(setSaved).catch(() => setSaved([]))
  }, [customer.id])

  return (
    <Modal title={`Замовлення: ${customer.first_name || customer.tg_id}`} onClose={onClose}>
      {!orders ? (
        <Loading rows={3} />
      ) : orders.length === 0 ? (
        <p className="muted">Клієнт ще нічого не замовляв.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>№</th>
                <th>Дата</th>
                <th>Склад</th>
                <th className="num">Сума</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td className="id-tag">#{o.id}</td>
                  <td className="faint">{date(o.created_at)}</td>
                  <td className="faint">{o.items.map((i) => `${i.name} ×${i.qty}`).join(', ')}</td>
                  <td className="num">{money(o.total)}</td>
                  <td className="muted">{STATUS_LABELS[o.status] || o.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {saved && saved.some((w) => w.products.length > 0) && (
        <div style={{ marginTop: 18 }}>
          <h3 style={{ marginBottom: 6 }}>Відкладене</h3>
          <p className="faint" style={{ marginTop: 0 }}>
            Товари, які клієнт зберіг на потім. Якщо чогось немає в наявності —
            це привід написати, коли з'явиться.
          </p>
          {saved.filter((w) => w.products.length > 0).map((list) => (
            <div key={list.id} style={{ marginBottom: 10 }}>
              <div className="faint">{list.name} · {list.size}</div>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {list.products.map((p) => (
                  <li key={p.id}>
                    {p.name} — {money(p.price)}
                    {!p.is_active && <span className="chip bad" style={{ marginLeft: 6 }}>прихований</span>}
                    {p.is_active && p.stock === 0 && (
                      <span className="chip warn" style={{ marginLeft: 6 }}>немає в наявності</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}

export default function Customers() {
  const notify = useToast()
  const [customers, setCustomers] = useState(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [bonusFor, setBonusFor] = useState(null)
  const [ordersFor, setOrdersFor] = useState(null)

  const load = useCallback(async () => {
    setError('')
    try {
      setCustomers(await api.customers.list({ search: search || undefined }))
    } catch (err) {
      setError(err.message)
    }
  }, [search])

  useEffect(() => {
    const timer = setTimeout(load, search ? 350 : 0)
    return () => clearTimeout(timer)
  }, [load, search])

  const toggleBlock = async (customer) => {
    try {
      const updated = await api.customers.patch(customer.id, { is_blocked: !customer.is_blocked })
      setCustomers((list) => list.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)))
      notify(updated.is_blocked ? 'Клієнта заблоковано' : 'Доступ відновлено')
    } catch (err) {
      notify(err.message, 'bad')
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Клієнти</h1>
          <p>Історія покупок, бонуси та реферальні коди</p>
        </div>
      </div>

      <div className="toolbar">
        <input
          className="input"
          placeholder="Ім'я, username або телефон"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <ErrorBar error={error} />

      {!customers ? (
        <Loading />
      ) : customers.length === 0 ? (
        <Empty title="Клієнтів немає">
          Тут з'являться всі, хто запустив бота.
        </Empty>
      ) : (
        <div className="card" style={{ padding: '18px 6px' }}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Клієнт</th>
                  <th>Реф. код</th>
                  <th className="num">Замовлень</th>
                  <th className="num">Витрачено</th>
                  <th className="num">Бонуси</th>
                  <th>З нами з</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {customers.map((c) => (
                  <tr key={c.id} style={c.is_blocked ? { opacity: 0.5 } : undefined}>
                    <td>
                      {c.first_name || '—'}
                      <div className="faint mono">
                        {c.username ? `@${c.username}` : `id${c.tg_id}`}
                        {c.phone ? ` · ${c.phone}` : ''}
                      </div>
                    </td>
                    <td className="mono">{c.referral_code}</td>
                    <td className="num">{c.orders_count}</td>
                    <td className="num">{money(c.total_spent)}</td>
                    <td className="num">{money(c.bonus_balance)}</td>
                    <td className="faint">{date(c.created_at)}</td>
                    <td>
                      <div className="row">
                        <button className="btn ghost small" onClick={() => setOrdersFor(c)}>Замовлення</button>
                        <button className="btn ghost small" onClick={() => setBonusFor(c)}>Бонуси</button>
                        <button
                          className={`btn small ${c.is_blocked ? 'ghost' : 'danger'}`}
                          onClick={() => toggleBlock(c)}
                        >
                          {c.is_blocked ? 'Розблокувати' : 'Заблокувати'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {bonusFor && (
        <BonusForm
          customer={bonusFor}
          onClose={() => setBonusFor(null)}
          onSaved={(updated) =>
            setCustomers((list) => list.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)))
          }
        />
      )}

      {ordersFor && <CustomerOrders customer={ordersFor} onClose={() => setOrdersFor(null)} />}
    </>
  )
}
