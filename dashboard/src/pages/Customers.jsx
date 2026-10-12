import { usePagedResource } from '../components/usePagedResource'
import { Pagination, PAGE_SIZE, pageNumber } from '../components/Pagination'
import { useCallback, useEffect, useState } from 'react'

import { api } from '../api'
import { useFilters } from '../components/useFilters'
import { OrderStatusBadge } from '../components/OrderStatus'
import { Empty, ErrorBar, Field, Loading, Modal, date, money, useToast } from '../components/ui'
import { useVisiblePolling } from '../components/useVisiblePolling'

function BonusForm({ customer, onClose, onSaved }) {
  const notify = useToast()
  const [amount, setAmount] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    if (busy) return
    setBusy(true)
    setError('')
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
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Змінити бонуси"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Скасувати</button>
          <button className="btn" onClick={save} disabled={busy || !amount || Number(amount) === 0}>
            {busy ? 'Застосовуємо…' : 'Застосувати'}
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
  const [page, setPage] = useState(1)
  const fetchOrders = useCallback(() => api.customers.orders(customer.id, {
    paginated: true, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE,
  }), [customer.id, page])
  const fetchSaved = useCallback(async () => {
    const items = await api.customers.wishlists(customer.id)
    return { items, total: items.length }
  }, [customer.id])
  const { data: orders, total, loading: ordersLoading, error: ordersError, load: loadOrders } = usePagedResource(
    JSON.stringify([customer.id, page]), fetchOrders)
  const { data: saved, loading: savedLoading, error: savedError, load: loadSaved } = usePagedResource(
    String(customer.id), fetchSaved)

  useEffect(() => {
    let timer = null
    const onOrderChanged = (event) => {
      if (Number(event.detail?.userId) !== Number(customer.id)) return
      if (timer) clearTimeout(timer)
      timer = setTimeout(loadOrders, 100)
    }
    window.addEventListener('elfar:orders:changed', onOrderChanged)
    return () => {
      if (timer) clearTimeout(timer)
      window.removeEventListener('elfar:orders:changed', onOrderChanged)
    }
  }, [customer.id, loadOrders])

  return (
    <Modal title={`Замовлення: ${customer.first_name || customer.tg_id}`} onClose={onClose}>
      <ErrorBar error={ordersError} />
      {ordersError && <div className="row"><span className="faint">{orders ? 'Попередні замовлення можуть бути застарілими.' : 'Замовлення не завантажено.'}</span><button className="btn ghost small" disabled={ordersLoading} onClick={loadOrders}>Повторити замовлення</button></div>}
      {orders && <Pagination page={page} total={total} count={orders.length} loading={ordersLoading} onPage={setPage} />}
      {!orders ? (
        ordersLoading ? <Loading rows={3} /> : null
      ) : orders.length === 0 && ordersError ? null : orders.length === 0 ? (
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
                  <td><OrderStatusBadge order={o} compact /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 style={{ marginTop: 18 }}>Збережені списки</h3>
      <ErrorBar error={savedError} />
      {savedError && <div className="row"><span className="faint">{saved ? 'Попередні списки можуть бути застарілими.' : 'Списки не завантажено.'}</span><button className="btn ghost small" disabled={savedLoading} onClick={loadSaved}>Повторити списки</button></div>}
      {savedLoading && !saved && <Loading rows={2} />}
      {saved && !savedError && !saved.some((w) => w.products.length > 0) && <p className="faint">Збережених товарів немає.</p>}
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
  const [{ search, page: rawPage }, setQuery, resetFilters] = useFilters({ search: '', page: 1 })
  const setSearch = (v) => setQuery('search', v)
  const [bonusFor, setBonusFor] = useState(null)
  const [ordersFor, setOrdersFor] = useState(null)

  const page = pageNumber(rawPage)
  const fetchPage = useCallback(() => api.customers.list({ search: search || undefined,
    paginated: true, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }), [search, page])
  const { data: customers, setData: setCustomers, total, loading, error, load } = usePagedResource(
    JSON.stringify([search, page]), fetchPage, search ? 350 : 0)

  useVisiblePolling(load, 30000)

  useEffect(() => {
    let timer = null
    const onOrderChanged = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => load(), 150)
    }
    window.addEventListener('elfar:orders:changed', onOrderChanged)
    return () => {
      if (timer) clearTimeout(timer)
      window.removeEventListener('elfar:orders:changed', onOrderChanged)
    }
  }, [load])

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
      {error && <div className="row"><span className="faint">{customers ? 'Показано попередні дані. Вони можуть бути застарілими.' : 'Дані не завантажено.'}</span><button className="btn ghost small" disabled={loading} onClick={load}>Спробувати ще раз</button></div>}
      {loading && customers && <p className="faint" role="status">Оновлюємо…</p>}
      {customers && <Pagination page={page} total={total} count={customers.length} loading={loading} onPage={(v) => setQuery('page', v)} />}

      {!customers ? (
        loading ? <Loading /> : null
      ) : customers.length === 0 && error ? null : customers.length === 0 ? (
        search ? (
          <Empty title="Нічого не знайдено">
            За запитом «{search}» клієнтів немає. Пошук працює за імʼям
            і номером телефону.
            <div style={{ marginTop: 12 }}>
              <button className="btn ghost small" onClick={resetFilters}>
                Очистити пошук
              </button>
            </div>
          </Empty>
        ) : (
          <Empty title="Клієнтів немає">
            Тут зʼявляться всі, хто запустив бота.
          </Empty>
        )
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

      {ordersFor && <CustomerOrders key={ordersFor.id} customer={ordersFor} onClose={() => setOrdersFor(null)} />}
    </>
  )
}
