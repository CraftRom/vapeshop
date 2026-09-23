import { memo, useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api, isSysadmin } from '../api'
import { STATUS_LABELS, allowedFrom } from '../components/StatusRail'
import { OrderStatusBadge, SalesDriveStatusSelect, isNewOrderStatus } from '../components/OrderStatus'
import { Empty, ErrorBar, Field, Info, Loading, Modal, dateTime, money, useToast } from '../components/ui'
import { useFilters } from '../components/useFilters'
import { useVisiblePolling } from '../components/useVisiblePolling'

// Той самий перелік, що й на сторінці замовлення.
const DELIVERY_METHODS = {
  warehouse: 'Відділення НП',
  courier: 'Курʼєр',
}

const LEGACY_FILTERS = [
  { value: 'new', label: 'Нове' },
  { value: 'accepted', label: 'Прийняте в роботу' },
  { value: 'paid', label: 'Оплачене' },
  { value: 'shipped', label: 'Відправлене' },
  { value: 'done', label: 'Виконане' },
  { value: 'cancelled', label: 'Скасоване' },
]

const PAYMENT_METHODS = {
  card: {
    title: 'Переказ на картку',
    hint: 'Клієнт обрав переказ',
    icon: '💳',
  },
  cod: {
    title: 'Накладений платіж',
    hint: 'Оплата при отриманні',
    icon: '📦',
  },
}

function OrderPaymentMethod({ order, compact = false }) {
  const method = order.payment_method === 'cod' ? 'cod' : 'card'
  const meta = PAYMENT_METHODS[method]

  return (
    <div
      className={`order-payment-method ${method}${compact ? ' compact' : ''}`}
      aria-label={`Спосіб оплати: ${meta.title}`}
    >
      <span className="order-payment-method-icon" aria-hidden="true">{meta.icon}</span>
      <span className="order-payment-method-copy">
        <small className="order-payment-method-kicker">Оплата</small>
        <strong>{meta.title}</strong>
        <small>{meta.hint}</small>
      </span>
    </div>
  )
}

function ukForm(value, one, few, many) {
  const count = Math.abs(Number(value || 0))
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

function OrderDetails({ order, onClose, onSaved, crmStatuses = [] }) {
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
        <div className="order-quick-status">
          <span className="faint">Актуальний статус</span>
          <OrderStatusBadge order={order} crmStatuses={crmStatuses} />
        </div>
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

        <div className="order-quick-payment">
          <OrderPaymentMethod order={order} />
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
              {(order.waybill_source === 'novaposhta' || String(order.crm_snapshot?.novaposhta?.ttn || '') === String(order.tracking_number)) ? (
                <a
                  className="info-strong num"
                  href={`https://novaposhta.ua/tracking/?cargo_number=${encodeURIComponent(order.tracking_number)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {order.tracking_number}
                </a>
              ) : (
                <span className="info-strong num">{order.tracking_number}</span>
              )}
            </Info>
          )}
          <Info label="Telegram">{contact}</Info>
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
  onQuickView,
  onCancel,
  onRemove,
  crmStatuses,
  onCrmStatusChange,
}) {
  const itemsText = order.items.map((i) => `${i.name} ×${i.qty}`).join(', ')
  const itemQty = order.items.reduce((sum, item) => sum + Number(item.qty || 0), 0)
  const isNewOrder = isNewOrderStatus(order, crmStatuses)

  return (
    <article className={`order-row ${order.crm_id ? 'status-crm' : `status-${order.status}`}${isNewOrder ? ' is-new-order' : ''}${unreadCount > 0 ? ' has-unread-messages' : ''}`}>
      <div className="order-primary">
        <div className="order-id-line">
          <Link to={`/orders/${order.id}`} className="id-tag">#{order.id}</Link>
          {unreadCount > 0 && (
            <Link
              to={`/orders/${order.id}#chat`}
              className="order-unread"
              title={`Від клієнта ${unreadCount} ${unreadCount === 1 ? 'нове повідомлення' : 'нових повідомлення'}`}
              aria-label={`Відкрити ${unreadCount} непрочитаних повідомлень замовлення №${order.id}`}
            >
              <span className="order-unread-dot" aria-hidden="true" />
              <span className="order-unread-label">{unreadCount === 1 ? 'Нове повідомлення' : `${unreadCount} нові повідомлення`}</span>
              <strong>{unreadCount}</strong>
            </Link>
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

      <div className="order-payment-cell">
        <OrderPaymentMethod order={order} compact />
      </div>

      <div className="order-workflow">
        <div className="order-status-title">
          <span className="faint">Поточний статус</span>
          <OrderStatusBadge order={order} crmStatuses={crmStatuses} />
          {isNewOrder && (
            <span className="order-new-flag" title="Замовлення ще має статус «Новий»">
              <span className="order-new-flag-dot" aria-hidden="true" />
              Нове замовлення
            </span>
          )}
        </div>
        {order.crm_id ? (
          <SalesDriveStatusSelect
            order={order}
            statuses={crmStatuses}
            onChange={(option) => onCrmStatusChange(order, option)}
          />
        ) : (
          <div className="legacy-status-note">Історичне замовлення · статус ведеться локально і не синхронізується з CRM</div>
        )}
        <div className="orders-actions">
          <Link className="btn small order-open" to={`/orders/${order.id}`}>
            Відкрити
          </Link>
          <button className="btn ghost small" onClick={() => onQuickView(order)}>
            Швидкий перегляд
          </button>
          {!order.crm_id && allowedFrom(order.status, order.payment_method).includes('cancelled') && (
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
  const [crmStatuses, setCrmStatuses] = useState([])
  const [crmStatusesError, setCrmStatusesError] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      const crmFilter = status.startsWith('crm:') ? status.slice(4) : ''
      const legacyFilter = status.startsWith('legacy:')
        ? status.slice(7)
        : LEGACY_FILTERS.some((item) => item.value === status) ? status : ''
      setOrders(await api.orders.list({
        crm_status_id: crmFilter || undefined,
        status: legacyFilter || undefined,
        legacy_only: legacyFilter ? true : undefined,
        search,
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

  const loadCrmStatuses = useCallback(async () => {
    try {
      const data = await api.orders.salesdriveStatuses()
      setCrmStatuses(Array.isArray(data?.statuses) ? data.statuses : [])
      setCrmStatusesError('')
    } catch (err) {
      // Не стираємо вже відомий довідник при короткому збої CRM: поточні
      // order.crm_status_* лишаються видимими, а менеджер бачить попередження.
      setCrmStatusesError(err.message || 'Не вдалося прочитати статуси SalesDrive')
    }
  }, [])

  useEffect(() => {
    loadCrmStatuses()
  }, [loadCrmStatuses])

  const loadUnread = useCallback(async () => {
    const next = await api.orders.unread()
    // Якщо цифри не змінились, не створюємо новий state і не запускаємо
    // зайвий рендер усієї сторінки.
    setUnread((prev) => (sameUnreadCounts(prev, next) ? prev : next))
  }, [])

  // Чат і CRM живі: unread має підтягуватися швидко, але прихована вкладка
  // не робить запитів завдяки useVisiblePolling.
  useVisiblePolling(loadUnread, 10000, { immediate: true })
  // Webhook оновлює crm_status_* у backend; список підтягує ці зміни без
  // перезавантаження сторінки. На прихованій вкладці polling зупиняється.
  useVisiblePolling(load, 15000)
  // Назви/набір статусів теж належать CRM. Вони змінюються рідко, тому
  // перечитуємо довідник окремо раз на 5 хвилин і одразу після повернення
  // на вкладку, не збільшуючи частоту важчого order-list API.
  useVisiblePolling(loadCrmStatuses, 300000)

  // Primary path: backend commit -> Redis -> authenticated SSE -> canonical
  // list reload. A tiny debounce collapses a multi-field CRM transition into
  // one request instead of refetching for every internal UPDATE.
  useEffect(() => {
    let timer = null
    const onOrderChanged = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => load(), 100)
    }
    window.addEventListener('elfar:orders:changed', onOrderChanged)
    return () => {
      if (timer) clearTimeout(timer)
      window.removeEventListener('elfar:orders:changed', onOrderChanged)
    }
  }, [load])

  // NotificationCenter remains a second independent invalidation path for
  // safety poll списку. Використовуємо її лише як invalidation-сигнал і
  // перечитуємо API — payload toast-а ніколи не стає джерелом order data.
  useEffect(() => {
    const onFreshNotification = (event) => {
      const items = Array.isArray(event.detail?.items) ? event.detail.items : []
      if (items.some((item) => item.kind === 'order.created')) load()
      if (items.some((item) => item.kind === 'order.message')) loadUnread().catch(() => {})
    }
    window.addEventListener('elfar:notifications:fresh', onFreshNotification)
    return () => window.removeEventListener('elfar:notifications:fresh', onFreshNotification)
  }, [load, loadUnread])

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

  const changeCrmStatus = useCallback(async (order, option) => {
    const previousId = order.crm_status_id
    const previousName = order.crm_status_name
    setOrders((list) => list?.map((o) => o.id === order.id ? { ...o, crm_status_id: String(option.id), crm_status_name: option.name } : o))
    try {
      const updated = await api.orders.salesdriveStatus(order.id, option.id)
      setOrders((list) => list?.map((o) => o.id === order.id ? updated : o))
      notify(`Замовлення №${order.id}: ${option.name}`)
    } catch (err) {
      setOrders((list) => list?.map((o) => o.id === order.id ? { ...o, crm_status_id: previousId, crm_status_name: previousName } : o))
      notify(err.message, 'bad')
    }
  }, [notify])

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
  // Summary описує саме видимий список. Якщо активний пошук/фільтр, не
  // обіцяємо «2 непрочитаних нижче», коли ці два замовлення відфільтровані.
  const unreadTotal = orders?.reduce((sum, order) => sum + Number(unread[order.id] || 0), 0) || 0
  const unreadOrders = orders?.filter((order) => Number(unread[order.id] || 0) > 0).length || 0
  const newOrders = orders?.filter((order) => isNewOrderStatus(order, crmStatuses)).length || 0


  return (
    <>
      <div className="page-head">
        <div>
          <h1>Замовлення</h1>
          <p>CRM-замовлення показують актуальний статус SalesDrive; legacy лишаються окремо</p>
        </div>
      </div>

      <div className="orders-toolbar">
        <div className="orders-filters">
          <label className="filter-field filter-status">
            <span>Статус</span>
            <select
              className="input"
              value={status && !status.includes(':') ? `legacy:${status}` : status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">Усі статуси</option>
              {crmStatuses.length > 0 && (
                <optgroup label="SalesDrive">
                  {crmStatuses.map((item) => (
                    <option key={item.id} value={`crm:${item.id}`}>{item.name}</option>
                  ))}
                </optgroup>
              )}
              <optgroup label="Legacy (старі замовлення)">
                {LEGACY_FILTERS.map((item) => (
                  <option key={item.value} value={`legacy:${item.value}`}>{item.label}</option>
                ))}
              </optgroup>
            </select>
            {crmStatusesError && <small className="filter-status-warning">CRM недоступна: показуємо останні збережені статуси</small>}
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
          <button className="btn ghost small" onClick={() => { load(); loadCrmStatuses() }}>Оновити</button>
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

          {(newOrders > 0 || unreadTotal > 0) && (
            <div className="orders-attention-summary" role="status" aria-label="Замовлення, що потребують уваги">
              {newOrders > 0 && (
                <div className="orders-attention-item new-orders">
                  <span className="orders-attention-dot" aria-hidden="true" />
                  <span>
                    <strong>{newOrders} {ukForm(newOrders, 'нове замовлення', 'нові замовлення', 'нових замовлень')}</strong>
                    <small>Ще мають початковий статус «Новий»</small>
                  </span>
                </div>
              )}
              {unreadTotal > 0 && (
                <div className="orders-attention-item unread-messages">
                  <span className="orders-attention-message" aria-hidden="true">💬</span>
                  <span>
                    <strong>{unreadTotal} {ukForm(unreadTotal, 'непрочитане повідомлення', 'непрочитані повідомлення', 'непрочитаних повідомлень')}</strong>
                    <small>У {unreadOrders} {ukForm(unreadOrders, 'замовленні', 'замовленнях', 'замовленнях')} · відкрийте рядок із синьою міткою</small>
                  </span>
                </div>
              )}
            </div>
          )}

          <div className="orders-list-head" aria-hidden="true">
            <span>Замовлення</span>
            <span>Клієнт</span>
            <span>Склад</span>
            <span className="num">Сума</span>
            <span>Оплата</span>
            <span>Статус і дії</span>
          </div>

          <div className="orders-list">
            {orders.map((order) => (
              <OrderRow
                key={order.id}
                order={order}
                unreadCount={Number(unread[order.id] || 0)}
                canDelete={canDelete}
                onQuickView={setSelected}
                onCancel={cancelOrder}
                onRemove={removeOrder}
                crmStatuses={crmStatuses}
                onCrmStatusChange={changeCrmStatus}
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
          crmStatuses={crmStatuses}
        />
      )}
    </>
  )
}
