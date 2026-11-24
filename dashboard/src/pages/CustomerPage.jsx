import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api'
import { customerName, customerSubtitle, phoneHref } from '../commerce'
import { OrderStatusBadge } from '../components/OrderStatus'
import { Pagination, PAGE_SIZE } from '../components/Pagination'
import { PageHeader, SectionCard } from '../components/page'
import { StateBadge } from '../components/StateBadge'
import { Empty, ErrorBar, Loading, date, dateTime, money, useToast } from '../components/ui'
import { usePagedResource } from '../components/usePagedResource'
import { EVENTS } from '../storageKeys'
import { BonusForm } from './Customers'

// Customer card: who the buyer is (Telegram profile),
// purchase statistics across all proven identities, order history and every
// conversation with them — order chats and support threads — in one place.

const SUPPORT_STATUS = { open: ['warning', 'відкрито'], closed: ['neutral', 'закрито'] }
const daysAgo = (iso) => iso ? Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)) : null
const ago = (iso) => {
  const days = daysAgo(iso)
  if (days === null) return ''
  return days === 0 ? 'сьогодні' : days === 1 ? 'вчора' : `${days} дн. тому`
}

function Metric({ label, value, sub, tone = '' }) {
  return <div className={`card metric ${tone}`}>
    <div className="label">{label}</div>
    <div className="value num">{value}</div>
    {sub && <div className="sub">{sub}</div>}
  </div>
}

function Shares({ title, rows, empty, render }) {
  const max = Math.max(1, ...rows.map((row) => row.value))
  return <SectionCard title={title} level={3}>
    {rows.length === 0 ? <p className="faint u-m-0">{empty}</p> : <ul className="customer-shares">
      {rows.map((row) => <li key={row.key}>
        <div className="row-between"><span>{row.label}</span><span className="faint num">{render(row)}</span></div>
        <div className="customer-share-bar" aria-hidden="true"><span style={{ width: `${Math.round(row.value / max * 100)}%` }} /></div>
      </li>)}
    </ul>}
  </SectionCard>
}

function Orders({ customerId }) {
  const [page, setPage] = useState(1)
  const fetchOrders = useCallback(() => api.customers.orders(customerId, {
    paginated: true, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE,
  }), [customerId, page])
  const { data: orders, total, loading, error, load } = usePagedResource(JSON.stringify([customerId, page]), fetchOrders)
  useEffect(() => {
    const onChanged = (event) => { if (Number(event.detail?.userId) === Number(customerId)) load() }
    window.addEventListener(EVENTS.ordersChanged, onChanged)
    return () => window.removeEventListener(EVENTS.ordersChanged, onChanged)
  }, [customerId, load])
  return <SectionCard title="Замовлення" description="Усі замовлення клієнта з Mini App і бота">
    <ErrorBar error={error} />
    {error && <button className="btn ghost small" disabled={loading} onClick={load}>Оновити замовлення</button>}
    {orders && <Pagination page={page} total={total} count={orders.length} loading={loading} onPage={setPage} />}
    {!orders ? (loading ? <Loading rows={3} /> : null) : orders.length === 0 ? (error ? null : <p className="muted">Клієнт ще нічого не замовляв.</p>) : (
      <div className="table-wrap"><table>
        <thead><tr><th>№</th><th>Дата</th><th>Склад</th><th className="num">Сума</th><th>Статус</th></tr></thead>
        <tbody>{orders.map((o) => <tr key={o.id}>
          <td><Link className="id-tag" to={`/orders/${o.id}`}>#{o.id}</Link></td>
          <td className="faint">{date(o.created_at)}</td>
          <td className="faint">{o.items.map((i) => `${i.name} ×${i.qty}`).join(', ')}</td>
          <td className="num">{money(o.total)}</td>
          <td><OrderStatusBadge order={o} compact /></td>
        </tr>)}</tbody>
      </table></div>
    )}
  </SectionCard>
}

function Chats({ summary }) {
  const { order_chats: orderChats, support_threads: threads } = summary
  const unread = orderChats.reduce((sum, chat) => sum + chat.unread, 0)
  return <SectionCard title="Чати з клієнтом" description={unread ? `Непрочитаних повідомлень: ${unread}` : 'Листування щодо замовлень і звернення в підтримку'}>
    {orderChats.length === 0 && threads.length === 0 ? <p className="faint u-m-0">Клієнт ще не писав.</p> : <ul className="customer-chats">
      {orderChats.map((chat) => <li key={'o' + chat.order_id}>
        <Link to={`/orders/${chat.order_id}`}>Чат замовлення #{chat.order_id}</Link>
        <span className="faint"> · {chat.messages} повід. · {dateTime(chat.last_message_at)}</span>
        {chat.unread > 0 && <StateBadge tone="warning" className="inline-badge">нових: {chat.unread}</StateBadge>}
      </li>)}
      {threads.map((thread) => {
        const [tone, label] = SUPPORT_STATUS[thread.status] || ['neutral', thread.status]
        return <li key={'s' + thread.id}>
          <Link to={`/support?thread=${thread.id}`}>Звернення в підтримку #{thread.id}</Link>
          <span className="faint"> · {dateTime(thread.last_message_at || thread.created_at)}</span>
          <StateBadge tone={tone} className="inline-badge">{label}</StateBadge>
        </li>
      })}
    </ul>}
  </SectionCard>
}

function Saved({ customerId }) {
  const [lists, setLists] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { api.customers.wishlists(customerId).then(setLists).catch((err) => setError(err.message)) }, [customerId])
  const filled = (lists || []).filter((list) => list.products.length > 0)
  return <SectionCard title="Відкладене" description="Товари, які клієнт зберіг на потім: привід написати, коли з'являться в наявності" level={3}>
    <ErrorBar error={error} />
    {!lists && !error && <Loading rows={2} />}
    {lists && filled.length === 0 && <p className="faint u-m-0">Збережених товарів немає.</p>}
    {filled.map((list) => <div key={list.id} className="u-mb-3">
      <div className="faint">{list.name} · {list.size}</div>
      <ul className="u-my-2">{list.products.map((p) => <li key={p.id}>
        {p.name} — {money(p.price)}
        {!p.is_active && <StateBadge tone="danger" className="inline-badge">прихований</StateBadge>}
        {p.is_active && p.stock === 0 && <StateBadge tone="warning" className="inline-badge">немає в наявності</StateBadge>}
      </li>)}</ul>
    </div>)}
  </SectionCard>
}

export default function CustomerPage() {
  const { id } = useParams()
  const notify = useToast()
  const [customer, setCustomer] = useState(null)
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState('')
  const [bonusOpen, setBonusOpen] = useState(false)

  const load = useCallback(() => {
    setError('')
    Promise.all([api.customers.get(id), api.customers.summary(id)])
      .then(([c, s]) => { setCustomer(c); setSummary(s) })
      .catch((err) => setError(err.message))
  }, [id])
  useEffect(() => { load() }, [load])

  if (error && !customer) return <>
    <p><Link to="/customers">← Клієнти</Link></p>
    <ErrorBar error={error} />
    <button className="btn ghost small" onClick={load}>Спробувати ще раз</button>
  </>
  if (!customer || !summary) return <Loading />

  const stats = summary.stats
  const toggleBlock = async () => {
    if (!customer.is_blocked && !window.confirm(`Заблокувати ${customerName(customer)}? Клієнт не зможе користуватися ботом і Mini App, доки доступ не відновлять.`)) return
    try {
      const updated = await api.customers.patch(customer.id, { is_blocked: !customer.is_blocked })
      setCustomer((old) => ({ ...old, ...updated }))
      notify(updated.is_blocked ? 'Клієнта заблоковано' : 'Доступ відновлено')
    } catch (err) { notify(err.message, 'bad') }
  }
  const phone = customer.phone
  const conversion = stats.orders ? Math.round(stats.sales / stats.orders * 100) : null
  const sinceLast = daysAgo(stats.last_order_at)

  return <>
    <p className="u-m-0"><Link to="/customers">← Клієнти</Link></p>
    <PageHeader
      title={customerName(customer)}
      description={customerSubtitle(customer)}
      actions={<>
        <button className="btn ghost" onClick={() => setBonusOpen(true)}>Змінити бонуси</button>
        <button className={`btn ${customer.is_blocked ? '' : 'danger'}`} onClick={toggleBlock}>{customer.is_blocked ? 'Розблокувати' : 'Заблокувати'}</button>
      </>}
    />
    <ErrorBar error={error} />

    <div className="customer-identity u-mb-4" aria-label="Як звʼязатися">
      {summary.telegram_connected && <StateBadge tone="success">Telegram</StateBadge>}
      {customer.is_blocked && <StateBadge tone="danger">заблокований</StateBadge>}
      {phone && <a href={phoneHref(phone)}>{phone}</a>}
      {customer.tg_id > 0 && customer.username && <a href={`https://t.me/${customer.username}`} target="_blank" rel="noopener noreferrer">@{customer.username}</a>}
      <span className="faint">клієнт з {date(customer.created_at)}</span>
      {customer.referral_code && <span className="faint">реф. код <span className="mono">{customer.referral_code}</span></span>}
    </div>

    <section className="grid k4 u-mb-4" aria-label="Статистика покупок">
      <Metric label="Сума покупок" value={money(stats.revenue)} sub={`завершених продажів: ${stats.sales}`} tone="accent" />
      <Metric label="Середній чек" value={stats.average_check ? money(stats.average_check) : '—'} sub={stats.average_order ? `середнє замовлення ${money(stats.average_order)}` : 'ще немає продажів'} />
      <Metric label="Замовлень" value={stats.orders} sub={conversion === null ? 'ще не замовляв' : `${conversion}% завершено продажем`} />
      <Metric label="Бонуси" value={money(stats.bonus_balance)} sub="поточний баланс" />
      <Metric label="Останнє замовлення" value={stats.last_order_at ? date(stats.last_order_at) : '—'} sub={ago(stats.last_order_at)} tone={sinceLast !== null && sinceLast > 90 ? 'warn' : ''} />
      <Metric label="Перше замовлення" value={stats.first_order_at ? date(stats.first_order_at) : '—'} sub={stats.first_order_at ? ago(stats.first_order_at) : ''} />
      <Metric label="Відмови й скасування" value={stats.lost} tone={stats.lost ? 'warn' : ''} sub={stats.orders ? `з ${stats.orders} замовлень` : ''} />
      <Metric label="Замовлено на суму" value={money(stats.ordered_sum)} sub="без скасованих" />
    </section>

    <div className="grid k3 u-mb-4 customer-columns">
      <Shares title="Улюблені категорії" empty="Покупок ще не було."
        rows={summary.categories.map((b) => ({ key: b.name, label: b.name, value: b.qty, amount: b.amount }))}
        render={(row) => `${row.value} шт. · ${money(row.amount)}`} />
      <Shares title="Найчастіше купує" empty="Покупок ще не було."
        rows={summary.products.map((p) => ({ key: p.name, label: p.name, value: p.qty }))}
        render={(row) => `${row.value} шт.`} />
      <Shares title="Звідки замовляє" empty="Замовлень ще не було."
        rows={summary.channels.map((c) => ({ key: c.key, label: c.label, value: c.orders }))}
        render={(row) => `${row.value} замовл.`} />
    </div>

    <Chats summary={summary} />
    <Orders customerId={customer.id} />
    <Saved customerId={customer.id} />
    {stats.orders === 0 && summary.order_chats.length === 0 && <Empty title="Поки без активності">Коли клієнт оформить замовлення або напише, тут з’явиться історія.</Empty>}

    {bonusOpen && <BonusForm customer={customer} onClose={() => setBonusOpen(false)} onSaved={(updated) => {
      setCustomer((old) => ({ ...old, ...updated }))
      setSummary((old) => ({ ...old, stats: { ...old.stats, bonus_balance: updated.bonus_balance } }))
    }} />}
  </>
}
