import { memo, useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api, isSysadmin } from '../api'
import StatusRail, { STATUS_LABELS, allowedFrom } from '../components/StatusRail'
import { Empty, ErrorBar, Field, Info, Loading, Modal, dateTime, money, useToast } from '../components/ui'
import { useFilters } from '../components/useFilters'
import { useVisiblePolling } from '../components/useVisiblePolling'

// Той самий перелік, що й на сторінці замовлення.
const DELIVERY_METHODS = {
  warehouse: 'Відділення НП',
  courier: 'Курʼєр',
}

const FILTERS = [
  { value: '', label: 'Усі' },
  { value: 'new', label: 'Нові' },
  // «Прийняті», а не «Підтверджені»: крок підтвердження прибрано, і саме
  // в «Прийнято» тепер стоїть більшість замовлень — його й треба вміти
  // відібрати. Фільтра на прибраний крок немає навмисно: він показував би
  // лише спадкові рядки, яких після міграції не лишилось.
  { value: 'accepted', label: 'Прийняті' },
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

  const fullName = [order.contact_surname, order.contact_name, order.contact_patronymic]
    .filter(Boolean).join(' ')
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
          <h3>Отримувач і доставка</h3>
          {/* Той самий вигляд, що й на сторінці замовлення: підпис
              зверху, значення знизу. Раніше все це йшло одним рядком
              через крапки, і телефон доводилось вишукувати очима
              посеред імені та адреси. */}
          <Info label="Прізвище, імʼя" copy={fullName}>{fullName}</Info>
          <Info label="Номер телефону" copy={order.contact_phone}>
            <a className="info-strong" href={`tel:${order.contact_phone}`}>
              {order.contact_phone}
            </a>
          </Info>
          <Info
            label={DELIVERY_METHODS[order.delivery_method] || 'Доставка'}
            copy={[order.delivery_city, order.delivery_address].filter(Boolean).join(', ')}
          >
            {order.delivery_city && <div>{order.delivery_city}</div>}
            <div className="info-strong">{order.delivery_address}</div>
          </Info>
          {order.tracking_number && (
            <Info label="Накладна" copy={order.tracking_number}>
              <a
                className="info-strong num"
                href={`https://novaposhta.ua/tracking/?cargo_number=${order.tracking_number}`}
                target="_blank"
                rel="noreferrer"
              >
                {order.tracking_number}
              </a>
            </Info>
          )}
          <Info label="Telegram">{contact}</Info>
          <Info label="Оплата">
            {order.payment_method === 'card' ? 'Переказ на картку' : 'Накладений платіж'}
          </Info>
          <Info label="Створено">{dateTime(order.created_at)}</Info>
          {order.comment && <Info label="Коментар покупця">{order.comment}</Info>}
        </div>

        <Field label="Нотатка менеджера" hint="Видно лише в панелі, клієнт її не бачить">
          <textarea className="input" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  )
}

function sameUnreadCounts(left, right) {
  const a = left || {}
  const b = right || {}
  const aKeys = Object.keys(a)
  const bKeys = Object.keys(b)
  if (aKeys.length !== bKeys.length) return false
  return aKeys.every((key) => Number(a[key] || 0) === Number(b[key] || 0))
}

/**
 * Окремий memo-рядок потрібен не заради мікрооптимізації. Сторінка регулярно
 * оновлює непрочитані повідомлення; раніше кожен такий poll заново рендерив
 * усі замовлення, складав довгі рядки товарів і будував рейки статусів.
 * Тепер перерендерюється лише рядок, у якого справді змінився order/unread.
 */
const OrderRow = memo(function OrderRow({
  order,
  unreadCount,
  canDelete,
  onStatusChange,
  onQuickView,
  onCancel,
  onRemove,
}) {
  const itemsText = order.items.map((i) => `${i.name} ×${i.qty}`).join(', ')
  const itemQty = order.items.reduce((sum, item) => sum + Number(item.qty || 0), 0)

  return (
    <article className={`order-row status-${order.status}`}>
      <div className="order-primary">
        <div className="order-id-line">
          <Link to={`/orders/${order.id}`} className="id-tag">#{order.id}</Link>
          {unreadCount > 0 && (
            <span
              className="chip order-unread"
              title="Непрочитані повідомлення від клієнта"
            >
              💬 {unreadCount}
            </span>
          )}
        </div>
        <div className="faint">{dateTime(order.created_at)}</div>
        <strong className="order-mobile-total mono">{money(order.total)}</strong>
      </div>

      <div className="order-customer">
        <strong>{order.contact_name}</strong>
        <a className="faint mono order-phone" href={`tel:${order.contact_phone}`}>
          {order.contact_phone}
        </a>
      </div>

      <div className="order-items" title={itemsText}>
        <div>{itemsText}</div>
        <span className="faint">{itemQty} шт. · {order.items.length} поз.</span>
      </div>

      <div className="order-total mono">{money(order.total)}</div>

      <div className="order-workflow">
        <div className="order-status-title">
          <span className="faint">Поточний статус</span>
          <strong>{STATUS_LABELS[order.status] || order.status}</strong>
          <span className="order-payment">
            {order.payment_method === 'card' ? 'Картка' : 'Накладений платіж'}
          </span>
        </div>
        <StatusRail
          status={order.status}
          paymentMethod={order.payment_method}
          onChange={(next) => onStatusChange(order, next)}
        />
        <div className="orders-actions">
          <Link className="btn small order-open" to={`/orders/${order.id}`}>
            Відкрити
          </Link>
          <button className="btn ghost small" onClick={() => onQuickView(order)}>
            Швидкий перегляд
          </button>
          {allowedFrom(order.status, order.payment_method).includes('cancelled') && (
            <button
              className="btn ghost small order-cancel"
              onClick={() => onCancel(order)}
            >
              Скасувати
            </button>
          )}
          {canDelete && (
            <button
              className="btn danger small"
              onClick={() => onRemove(order)}
            >
              Стерти
            </button>
          )}
        </div>
      </div>
    </article>
  )
})

export default function Orders() {
  const navigate = useNavigate()
  const notify = useToast()
  const [orders, setOrders] = useState(null)
  // Фільтри — в адресі сторінки. Менеджер відбирає замовлення, відкриває
  // одне, повертається — і відбір на місці. З useState він щоразу
  // скидався, а за зміну таких повернень десятки.
  const [{ status, dateFrom, dateTo, search }, setFilter, resetFilters] = useFilters(
    { status: '', dateFrom: '', dateTo: '', search: '' },
  )
  const setStatus = (v) => setFilter('status', v)
  const setDateFrom = (v) => setFilter('dateFrom', v)
  const setDateTo = (v) => setFilter('dateTo', v)
  const setSearch = (v) => setFilter('search', v)
  const filtered = Boolean(status || dateFrom || dateTo || search)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)
  // Клієнт відповідає в боті, тож панель має сама помічати нові повідомлення
  const [unread, setUnread] = useState({})

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

  const loadUnread = useCallback(async () => {
    const next = await api.orders.unread()
    // Якщо цифри не змінились, не створюємо новий state і не запускаємо
    // зайвий рендер усієї сторінки.
    setUnread((prev) => (sameUnreadCounts(prev, next) ? prev : next))
  }, [])

  // Раніше setInterval будив приховану вкладку кожні 20 секунд. 45 секунд
  // достатньо для індикатора у списку, а повернення на вкладку оновлює його
  // негайно через useVisiblePolling.
  useVisiblePolling(loadUnread, 45000, { immediate: true })

  const changeStatus = useCallback(async (order, next) => {
    // Відправлення потребує накладної, а вікно для неї — на сторінці
    // замовлення. Без цього менеджер тиснув би тут і отримував відмову.
    if (next === 'shipped') {
      navigate(`/orders/${order.id}?ship=1`)
      return
    }

    const previousStatus = order.status
    setOrders((list) => list?.map((o) => (
      o.id === order.id ? { ...o, status: next } : o
    )))
    try {
      await api.orders.patch(order.id, { status: next })
      notify(`Замовлення №${order.id}: ${STATUS_LABELS[next]}`)
    } catch (err) {
      // Відкочуємо тільки змінений рядок. Знімок усього масиву робив callback
      // залежним від orders і ламав memo-оптимізацію рядків.
      setOrders((list) => list?.map((o) => (
        o.id === order.id ? { ...o, status: previousStatus } : o
      )))
      notify(err.message, 'bad')
    }
  }, [navigate, notify])

  /** Видалення замовлення. Тільки системний адміністратор.
   *
   * Менеджерам цього не дають навмисно: замовлення — первинний документ.
   * Помилкове скасовують статусом, так лишається слід. Стирати доводиться
   * хіба що тестові записи після налаштування.
   */
  const cancelOrder = useCallback(async (order) => {
    // Підтвердження тут не формальність: скасування повертає товар на
    // склад і бонуси клієнту, а зворотного шляху зі «Скасованого» немає.
    if (!window.confirm(
      `Скасувати замовлення №${order.id} на ${money(order.total)}? `
      + 'Товар повернеться в наявність, бонуси — клієнту. '
      + 'Повернути замовлення в роботу після цього не можна.',
    )) return
    await changeStatus(order, 'cancelled')
  }, [changeStatus])

  const removeOrder = useCallback(async (order) => {
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
  }, [load, notify])

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

  // Роль однакова для всіх рядків. Не читаємо й не JSON.parse-имо session
  // з localStorage всередині map для кожного замовлення.
  const canDelete = isSysadmin()


  return (
    <>
      <div className="page-head">
        <div>
          <h1>Замовлення</h1>
          <p>Клік по етапу переводить замовлення далі — клієнт одразу отримає сповіщення</p>
        </div>
      </div>

      <div className="orders-toolbar">
        <div className="orders-filters">
          <label className="filter-field filter-status">
            <span>Статус</span>
            <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
              {FILTERS.map((f) => (
                <option key={f.value} value={f.value}>{f.label}</option>
              ))}
            </select>
          </label>
          <label className="filter-field filter-search">
            <span>Пошук</span>
            <input
              className="input"
              type="search"
              placeholder="Ім'я або телефон"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label className="filter-field filter-date">
            <span>Від</span>
            <input
              className="input"
              type="date"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </label>
          <label className="filter-field filter-date">
            <span>До</span>
            <input
              className="input"
              type="date"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </label>
        </div>
        <div className="orders-toolbar-actions">
          {(dateFrom || dateTo) && (
            <button
              className="btn ghost small"
              onClick={() => { setDateFrom(''); setDateTo('') }}
            >
              Скинути дати
            </button>
          )}
          <button className="btn ghost small" onClick={load}>Оновити</button>
          {isSysadmin() && (
            <button className="btn danger small" onClick={purgeAll}>
              Стерти всі
            </button>
          )}
        </div>
      </div>

      <ErrorBar error={error} />

      {!orders ? (
        <Loading />
      ) : orders.length === 0 ? (
        /* Порожньо через фільтр і порожньо взагалі — різні речі, а текст
           був один. Менеджер відбирав за датою, нічого не знаходив і читав
           «щойно клієнт оформить замовлення, воно зʼявиться тут» — тобто
           панель повідомляла, що замовлень у магазині немає жодного. */
        filtered ? (
          <Empty title="Нічого не знайдено">
            За цим відбором замовлень немає. Спробуйте розширити діапазон
            дат або очистити пошук.
            <div style={{ marginTop: 12 }}>
              <button className="btn ghost small" onClick={resetFilters}>
                Скинути відбір
              </button>
            </div>
          </Empty>
        ) : (
          <Empty title="Замовлень немає">
            Щойно клієнт оформить замовлення в боті, воно зʼявиться тут.
          </Empty>
        )
      ) : (
        <section className="orders-panel" aria-label="Список замовлень">
          {filtered && (
            <div className="orders-result-bar">
              <span>Знайдено: <strong>{orders.length}</strong></span>
              <button className="btn ghost small" onClick={resetFilters}>
                Скинути відбір
              </button>
            </div>
          )}

          <div className="orders-list-head" aria-hidden="true">
            <span>Замовлення</span>
            <span>Клієнт</span>
            <span>Склад</span>
            <span className="num">Сума</span>
            <span>Статус і дії</span>
          </div>

          <div className="orders-list">
            {orders.map((order) => (
              <OrderRow
                key={order.id}
                order={order}
                unreadCount={Number(unread[order.id] || 0)}
                canDelete={canDelete}
                onStatusChange={changeStatus}
                onQuickView={setSelected}
                onCancel={cancelOrder}
                onRemove={removeOrder}
              />
            ))}
          </div>
        </section>
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
