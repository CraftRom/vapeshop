import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api, getToken } from '../api'
import { ErrorBar, Field, Info, Loading, Modal, money, useToast } from '../components/ui'
import { STATUS_LABELS, allowedFrom } from '../components/StatusRail'
import { OrderStatusBadge, SalesDriveStatusSelect } from '../components/OrderStatus'
import { useVisiblePolling } from '../components/useVisiblePolling'

// Спосіб доставки, обраний покупцем. Порожнє значення — замовлення з
// часів, коли вибору не було: тоді все писалося одним рядком адреси.
const DELIVERY_METHODS = {
  warehouse: 'Відділення НП',
  courier: 'Курʼєр',
}


function timestamp(value) {
  if (!value) return ''
  return new Date(value).toLocaleString('uk-UA', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

const FILE_LABEL = {
  photo: 'Фото', document: 'Документ', video: 'Відео', voice: 'Голосове',
}

/** Вкладення з Telegram.
 *
 * Файл віддає бекенд, і запит потребує токена — тож картинку не можна
 * просто підставити в src. Тягнемо як blob і показуємо з обʼєктного URL.
 */
function Attachment({ orderId, message }) {
  const [url, setUrl] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let revoked = null
    let cancelled = false
    fetch(api.orders.fileUrl(orderId, message.id), {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((blob) => {
        if (cancelled) return
        revoked = URL.createObjectURL(blob)
        setUrl(revoked)
      })
      .catch((err) => !cancelled && setFailed(err.message === '410' ? 'gone' : true))
    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [orderId, message.id])

  const label = FILE_LABEL[message.file_kind] || 'Файл'

  if (failed) {
    return (
      <div className="faint" style={{ fontSize: 12.5 }}>
        {failed === 'gone'
          // Не поломка, а строк зберігання: коди вкладень виконаних
          // замовлень прибираються через три дні, щоб база не тримала
          // доступу до чужих квитанцій довше, ніж це комусь потрібно.
          ? `${label} прибрано за строком зберігання`
          : `${label} недоступний — Telegram видаляє старі вкладення`}
      </div>
    )
  }
  if (!url) return <div className="faint" style={{ fontSize: 12.5 }}>{label} завантажується…</div>

  if (message.file_kind === 'photo') {
    return (
      <a href={url} target="_blank" rel="noreferrer">
        <img src={url} alt={label} className="bubble-photo" />
      </a>
    )
  }
  if (message.file_kind === 'voice') {
    return <audio controls src={url} style={{ width: '100%', marginTop: 6 }} />
  }
  if (message.file_kind === 'video') {
    return <video controls src={url} className="bubble-photo" />
  }
  return (
    <a href={url} download={message.file_name || 'file'} className="btn ghost small"
       style={{ marginTop: 6, display: 'inline-block' }}>
      ↓ {message.file_name || label}
    </a>
  )
}

/** Вікно введення накладної.
 *
 * Раніше менеджер мусив спершу вписати номер у поле нижче, а тоді натиснути
 * «Відправлено» — і без цього отримував відмову. Порядок неочевидний, тож
 * запитуємо номер саме тоді, коли він потрібен.
 */
function TrackingModal({ initial, onCancel, onConfirm }) {
  const [value, setValue] = useState(initial || '')
  const [busy, setBusy] = useState(false)

  const confirm = async () => {
    setBusy(true)
    await onConfirm(value.trim())
    setBusy(false)
  }

  return (
    <Modal
      title="Відправлення замовлення"
      onClose={onCancel}
      footer={
        <>
          <button className="btn ghost" onClick={onCancel}>Скасувати</button>
          <button className="btn" onClick={confirm} disabled={busy || !value.trim()}>
            {busy ? 'Надсилаємо…' : 'Відправити й надіслати ТТН'}
          </button>
        </>
      }
    >
      <Field
        label="Номер накладної"
        hint="Клієнт отримає його в Telegram одразу після підтвердження"
      >
        <input
          className="input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="20450912345678"
          autoFocus
          onKeyDown={(e) => e.key === 'Enter' && value.trim() && confirm()}
        />
      </Field>
    </Modal>
  )
}

function Chat({ orderId, messages, onSent }) {
  const notify = useToast()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const bottom = useRef(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const send = async () => {
    const body = text.trim()
    if (!body) return
    setBusy(true)
    try {
      const result = await api.orders.sendMessage(orderId, body)
      setText('')
      // Клієнт міг заблокувати бота — повідомлення збережеться, але не дійде
      if (!result.delivered) notify(result.warning || 'Не доставлено клієнту', 'bad')
      onSent()
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  const onKeyDown = (e) => {
    // Enter надсилає, Shift+Enter — новий рядок
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Листування</h2>

      <div className="chat-log">
        {messages.length === 0 ? (
          <p className="faint" style={{ margin: 0 }}>
            Повідомлень ще немає. Клієнт отримає ваше в чаті з ботом і зможе
            відповісти прямо звідти.
          </p>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`bubble ${m.direction === 'out' ? 'mine' : ''}`}>
              <div className="bubble-head faint">
                {m.direction === 'out' ? m.author || 'Менеджер' : m.author || 'Клієнт'}
                {' · '}
                {timestamp(m.created_at)}
              </div>
              {m.text && <div className="bubble-text">{m.text}</div>}
              {m.file_kind && <Attachment orderId={orderId} message={m} />}
              {/* Квитанція про прочитання — лише на своїх повідомленнях.
                  Без неї мовчання клієнта нічого не означає: незрозуміло,
                  чи він читає й не відповідає, чи просто не відкривав
                  застосунок, і чи варто дзвонити. */}
              {m.direction === 'out' && (
                <div className={`receipt ${m.is_read ? 'seen' : ''}`}>
                  {m.is_read ? '✓✓ Прочитано' : '✓ Надіслано'}
                </div>
              )}
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>

      <textarea
        className="input"
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Повідомлення клієнту. Enter — надіслати, Shift+Enter — новий рядок"
      />
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 10 }}>
        <button className="btn" onClick={send} disabled={busy || !text.trim()}>
          {busy ? 'Надсилаємо…' : 'Надіслати'}
        </button>
      </div>
    </div>
  )
}

const WAYBILL_SOURCE = {
  novaposhta: 'створена з панелі',
  salesdrive: 'з SalesDrive',
  manual: 'вписана вручну',
}

const CRM_STATE = {
  synced: { label: 'синхронізовано', tone: 'ok' },
  pending: { label: 'у черзі', tone: '' },
  creating: { label: 'створюється', tone: '' },
  uncertain: { label: 'перевіряється', tone: 'warn' },
  failed: { label: 'помилка', tone: 'bad' },
}

/** Накладна й SalesDrive в одному блоці.
 *
 * Одна накладна на замовлення: створена кнопкою, прийнята з CRM чи вписана
 * руками — усе це ті самі поля, тож і показуються вони в одному місці.
 * Причину, чому ТТН зараз не створити, показуємо ДО натискання: відмова
 * «впишіть телефон відправника» корисніша за вимкнену кнопку без пояснень.
 */
function WaybillPanel({ order, busy, onChanged }) {
  const notify = useToast()
  const [readiness, setReadiness] = useState(null)
  const [working, setWorking] = useState(false)

  useEffect(() => {
    let cancelled = false
    if (order.tracking_number) {
      setReadiness(null)
      return undefined
    }
    api.orders.waybillReadiness(order.id)
      .then((data) => { if (!cancelled) setReadiness(data) })
      .catch(() => { if (!cancelled) setReadiness(null) })
    return () => { cancelled = true }
  }, [order.id, order.tracking_number, order.status])

  const run = async (action, okText) => {
    setWorking(true)
    try {
      const fresh = await action()
      onChanged(fresh)
      notify(okText)
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setWorking(false)
    }
  }

  const printLabel = async () => {
    setWorking(true)
    try {
      const response = await fetch(api.orders.waybillLabelUrl(order.id), {
        headers: { Authorization: `Bearer ${getToken()}` },
      })
      if (!response.ok) {
        let detail = 'Не вдалося отримати маркування'
        try { detail = (await response.json()).detail || detail } catch { /* не JSON */ }
        throw new Error(detail)
      }
      const url = URL.createObjectURL(await response.blob())
      window.open(url, '_blank', 'noopener')
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setWorking(false)
    }
  }

  const crm = CRM_STATE[order.crm_state]
  const disabled = busy || working

  return (
    <div className="waybill-panel">
      {order.tracking_number ? (
        <div className="row-between waybill-row">
          <div>
            <div className="num info-strong">{order.tracking_number}</div>
            <div className="faint">
              ТТН {WAYBILL_SOURCE[order.waybill_source] || 'без джерела'}
              {order.waybill_cost ? ` · доставка ${Number(order.waybill_cost).toFixed(0)} грн` : ''}
            </div>
          </div>
          {order.waybill_source === 'novaposhta' && (
            <div className="row">
              <button className="btn ghost small" disabled={disabled} onClick={printLabel}>
                Маркування
              </button>
              {!['shipped', 'done'].includes(order.status) && (
                <button
                  className="btn ghost small danger"
                  disabled={disabled}
                  onClick={() => {
                    if (confirm(`Видалити ТТН ${order.tracking_number} у Новій пошті?`)) {
                      run(() => api.orders.deleteWaybill(order.id), 'Накладну видалено')
                    }
                  }}
                >
                  Видалити ТТН
                </button>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="waybill-row">
          <button
            className="btn"
            disabled={disabled || !readiness?.ready}
            onClick={() => run(() => api.orders.createWaybill(order.id), 'ТТН створено')}
          >
            {working ? 'Створення…' : 'Створити ТТН Нової пошти'}
          </button>
          {readiness && !readiness.ready && (
            <p className="faint waybill-hint">{readiness.problem}</p>
          )}
        </div>
      )}

      {crm && (
        <div className="row-between waybill-row">
          <span className="faint">
            SalesDrive: <span className={`chip ${crm.tone}`}>{crm.label}</span>
            {order.crm_id ? <span className="num"> · заявка {order.crm_id}</span> : null}
          </span>
          {['failed', 'uncertain'].includes(order.crm_state) && (
            <button
              className="btn ghost small"
              disabled={disabled}
              onClick={() => run(() => api.orders.crmSync(order.id), 'Відправлено в SalesDrive')}
            >
              Повторити
            </button>
          )}
        </div>
      )}
      {order.crm_error && <p className="faint waybill-hint bad-text">{order.crm_error}</p>}
    </div>
  )
}

export default function OrderPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const notify = useToast()

  const [order, setOrder] = useState(null)
  const [messages, setMessages] = useState([])
  const [error, setError] = useState('')
  const [tracking, setTracking] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [askTracking, setAskTracking] = useState(false)
  const [crmStatuses, setCrmStatuses] = useState([])
  const [crmRefreshing, setCrmRefreshing] = useState(false)
  const [crmAutoRefreshed, setCrmAutoRefreshed] = useState(false)

  const load = useCallback(async () => {
    try {
      const [fresh, log] = await Promise.all([
        api.orders.get(id),
        api.orders.messages(id, true),
      ])
      setOrder(fresh)
      setMessages(log)
      setTracking(fresh.tracking_number || '')
      setNote(fresh.admin_note || '')
    } catch (err) {
      setError(err.message)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const loadCrmStatuses = useCallback(async () => {
    try {
      const data = await api.orders.salesdriveStatuses()
      setCrmStatuses(Array.isArray(data?.statuses) ? data.statuses : [])
    } catch {
      // Коротка недоступність CRM не має прибирати вже завантажені назви.
    }
  }, [])

  useEffect(() => {
    loadCrmStatuses()
  }, [loadCrmStatuses])

  const refreshCrm = useCallback(async (quiet = false) => {
    if (!order?.crm_id || crmRefreshing) return
    setCrmRefreshing(true)
    try {
      const fresh = await api.orders.salesdriveRefresh(order.id)
      setOrder(fresh)
      setTracking(fresh.tracking_number || '')
      if (!quiet) notify('Дані SalesDrive оновлено')
    } catch (err) {
      if (!quiet) notify(err.message, 'bad')
    } finally {
      setCrmRefreshing(false)
    }
  }, [order?.id, order?.crm_id, crmRefreshing, notify])

  useEffect(() => {
    if (order?.crm_id && !crmAutoRefreshed) {
      setCrmAutoRefreshed(true)
      refreshCrm(true)
    }
  }, [order?.crm_id, crmAutoRefreshed, refreshCrm])

  // Поки картка відкрита, періодично перечитуємо саме заявку SalesDrive.
  // 120 с не перевантажує order-list API, але не залишає менеджеру старий
  // статус після зміни в CRM з іншої вкладки/телефону.
  useVisiblePolling(() => refreshCrm(true), 120000, { enabled: Boolean(order?.crm_id) })
  useVisiblePolling(loadCrmStatuses, 300000, { enabled: Boolean(order?.crm_id) })

  // Прийшли зі списку по кнопці «Відпр.» — одразу питаємо накладну
  useEffect(() => {
    if (order && params.get('ship') === '1' && order.status !== 'shipped') {
      setAskTracking(true)
      setParams({}, { replace: true })
    }
  }, [order, params, setParams])

  // Відповідь клієнта приходить у бот, а не в панель. Першу історію вже
  // забрав load(), тому тут лише фонове оновлення. У прихованій вкладці
  // таймера немає взагалі, а після повернення стрічка оновлюється одразу.
  const pollMessages = useCallback(async () => {
    const fresh = await api.orders.messages(id)
    setMessages(fresh)
  }, [id])
  useVisiblePolling(pollMessages, 15000)

  const patch = async (payload, okText) => {
    setBusy(true)
    try {
      const fresh = await api.orders.patch(id, payload)
      setOrder(fresh)
      notify(okText)
      load()
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  const changeStatus = async (status) => {
    // Накладну питаємо у вікні: це єдиний статус, який без неї не має сенсу
    if (status === 'shipped') {
      setAskTracking(true)
      return
    }
    await patch({ status }, 'Статус змінено')
  }

  const confirmShipping = async (value) => {
    setTracking(value)
    await patch(
      { status: 'shipped', tracking_number: value },
      'Відправлено, ТТН надіслано клієнту',
    )
    setAskTracking(false)
  }

  if (error && !order) return <ErrorBar error={error} />
  if (!order) return <Loading />

  const client = order.user || {}
  // Прізвище першим: саме в такому порядку його вписують у накладну, і
  // саме так його шукає менеджер у списку відправлень перевізника.
  const fullName = [order.contact_surname, order.contact_name, order.contact_patronymic]
    .filter(Boolean).join(' ')

  const paymentMethod = order.payment_method === 'cod' ? 'cod' : 'card'
  const paymentIsConfirmed = paymentMethod === 'card'
    && ['paid', 'shipped', 'done'].includes(order.status)
  const paymentIsCancelled = order.status === 'cancelled'
  const paymentTitle = paymentMethod === 'cod' ? 'Накладений платіж' : 'Переказ на картку'
  const paymentState = paymentIsCancelled
    ? 'Замовлення скасовано'
    : paymentMethod === 'cod'
      ? 'Оплата при отриманні'
      : paymentIsConfirmed
        ? 'Оплату підтверджено'
        : 'Очікує підтвердження оплати'
  const paymentHint = paymentIsCancelled
    ? 'Спосіб оплати збережено для історії замовлення. Додаткових дій з оплатою не потрібно.'
    : paymentMethod === 'cod'
      ? 'Клієнт сплачує при отриманні. Етап «Оплачено» для цього замовлення не використовується.'
      : paymentIsConfirmed
        ? 'Кошти вже позначені як отримані. Замовлення можна готувати до відправлення за звичайним маршрутом.'
        : 'Перед відправленням перевірте фактичне надходження коштів і переведіть замовлення в статус «Оплачено».'

  return (
    <>
      <div className="page-head">
        <div>
          <button className="btn ghost small" onClick={() => navigate('/orders')}>
            ← До списку
          </button>
          <h1 style={{ marginTop: 8 }}>Замовлення №{order.id}</h1>
          <div className="order-head-meta">
            <span>{timestamp(order.created_at)}</span>
            <span className={`order-head-payment ${paymentMethod}`}>
              {paymentMethod === 'cod' ? '📦' : '💳'} {paymentTitle}
            </span>
            {order.operator_name && <span>веде {order.operator_name}</span>}
          </div>
        </div>
      </div>

      <ErrorBar error={error} />

      <div className="order-grid">
        <div>
          <div className="card" style={{ marginBottom: 18 }}>
            <h2 style={{ marginTop: 0 }}>Статус</h2>

            <section
              className={`order-payment-summary ${paymentMethod} ${paymentIsConfirmed ? 'confirmed' : ''} ${paymentIsCancelled ? 'cancelled' : ''}`}
              aria-label={`Спосіб оплати: ${paymentTitle}`}
            >
              <div className="order-payment-icon" aria-hidden="true">
                {paymentMethod === 'cod' ? '📦' : '💳'}
              </div>
              <div className="order-payment-main">
                <div className="order-payment-kicker">Спосіб оплати</div>
                <div className="order-payment-title">{paymentTitle}</div>
                <div className="order-payment-state">
                  <span className="order-payment-state-dot" aria-hidden="true" />
                  {paymentState}
                </div>
                <p className="order-payment-hint">{paymentHint}</p>
              </div>
              <div className="order-payment-amount">
                <span>{paymentIsCancelled ? 'Сума замовлення' : paymentMethod === 'cod' ? 'До сплати при отриманні' : 'Сума замовлення'}</span>
                <strong className="num">{money(order.total)}</strong>
              </div>
            </section>

            <div className="order-current-status">
              <div>
                <span className="faint">Актуальний статус замовлення</span>
                <OrderStatusBadge order={order} crmStatuses={crmStatuses} />
              </div>
              {order.crm_id && (
                <span className="faint order-status-freshness">
                  {order.crm_fetched_at ? `Прочитано з CRM: ${timestamp(order.crm_fetched_at)}` : 'Очікує першого читання з CRM'}
                </span>
              )}
            </div>

            {order.crm_id ? (
              <div className="order-status-actions">
                <label className="faint" htmlFor="crm-order-status">Змінити статус у SalesDrive</label>
                <SalesDriveStatusSelect
                  order={order}
                  statuses={crmStatuses}
                  disabled={busy}
                  onChange={async (option) => {
                    setBusy(true)
                    try {
                      const fresh = await api.orders.salesdriveStatus(order.id, option.id)
                      setOrder(fresh)
                      notify(`Статус SalesDrive: ${fresh.crm_status_name || option.name}`)
                    } catch (err) { notify(err.message, 'bad') }
                    finally { setBusy(false) }
                  }}
                />
              </div>
            ) : (
              <div className="legacy-status-note">Legacy-статус: {STATUS_LABELS[order.status] || order.status}. Це історичне замовлення без звʼязку із SalesDrive.</div>
            )}

            {order.crm_id && (
              <section className="crm-live-card" aria-label="Актуальні дані SalesDrive">
                <div className="crm-live-head">
                  <div>
                    <div className="order-payment-kicker">SalesDrive · заявка {order.crm_id}</div>
                    <OrderStatusBadge order={order} crmStatuses={crmStatuses} compact />
                    <div className="faint">{order.crm_fetched_at ? `Прочитано з CRM: ${timestamp(order.crm_fetched_at)}` : 'Ще не читали стан заявки через API'}</div>
                  </div>
                  <button className="btn ghost small" disabled={crmRefreshing} onClick={() => { refreshCrm(false); loadCrmStatuses() }}>
                    {crmRefreshing ? 'Оновлення…' : 'Оновити з CRM'}
                  </button>
                </div>
                {order.crm_snapshot && (() => {
                  const c = order.crm_snapshot.contact || {}
                  const np = order.crm_snapshot.novaposhta || {}
                  const products = Array.isArray(order.crm_snapshot.products) ? order.crm_snapshot.products : []
                  return (
                    <>
                      <div className="crm-live-grid">
                        <div><span>Оплата</span><strong>{order.crm_snapshot.paymentMethod || '—'}</strong></div>
                        <div><span>Доставка</span><strong>{order.crm_snapshot.shippingMethod || '—'}</strong></div>
                        <div><span>Менеджер</span><strong>{order.crm_snapshot.managerName || (order.crm_snapshot.managerId ? `ID ${order.crm_snapshot.managerId}` : '—')}</strong></div>
                        <div><span>Сума CRM</span><strong>{order.crm_snapshot.paymentAmount ?? '—'}</strong></div>
                        <div><span>Оплачено</span><strong>{order.crm_snapshot.payedAmount ?? '—'}</strong></div>
                        <div><span>Залишок</span><strong>{order.crm_snapshot.restPay ?? '—'}</strong></div>
                        <div><span>Одержувач</span><strong>{[c.lName,c.fName,c.mName].filter(Boolean).join(' ') || '—'}</strong></div>
                        <div><span>Телефон CRM</span><strong>{c.phone || '—'}</strong></div>
                        <div><span>ТТН</span><strong>{np.ttn || '—'}</strong></div>
                        <div><span>Статус доставки</span><strong>{np.status || '—'}</strong></div>
                      </div>
                      {products.length > 0 && <div className="crm-live-products">
                        <span className="faint">Товари в заявці SalesDrive</span>
                        {products.map((p, i) => <div key={`${p.id || p.sku || i}-${i}`}><strong>{p.name || 'Товар'}</strong><span>{p.sku ? `SKU ${p.sku} · ` : ''}{p.amount ?? '—'} шт. · {p.price ?? '—'}</span></div>)}
                      </div>}
                    </>
                  )
                })()}
                <p className="faint crm-live-note">Це read-only snapshot заявки CRM. Ціни каталогу ELFAR з нього не змінюються.</p>
              </section>
            )}

            {!order.crm_id && allowedFrom(order.status, order.payment_method).includes('cancelled') && (
              <button
                className="btn danger small"
                style={{ marginTop: 10 }}
                disabled={busy}
                onClick={() => {
                  // Скасування необоротне: повертає залишки й бонуси,
                  // а зворотного шляху зі скасованого немає
                  if (confirm(`Скасувати замовлення №${order.id}? Це необоротно.`)) {
                    changeStatus('cancelled')
                  }
                }}
              >
                Скасувати замовлення
              </button>
            )}

            <WaybillPanel order={order} busy={busy} onChanged={(fresh) => { setOrder(fresh); setTracking(fresh.tracking_number || ''); load() }} />

            <Field
              label="Номер накладної"
              hint="Вписати вручну, якщо ТТН створено в кабінеті перевізника чи в SalesDrive. При переході в «Відправлено» надсилається клієнту автоматично"
            >
              <div className="row">
                <input
                  className="input"
                  value={tracking}
                  onChange={(e) => setTracking(e.target.value)}
                  placeholder="20450912345678"
                />
                <button
                  className="btn ghost"
                  disabled={busy || !tracking.trim() || tracking.trim() === order.tracking_number}
                  onClick={() => patch({ tracking_number: tracking.trim() }, 'Накладну збережено')}
                >
                  Зберегти
                </button>
              </div>
            </Field>

            <Field label="Нотатка менеджера" hint="Клієнт її не бачить">
              <textarea
                className="input"
                rows={2}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>
            <button
              className="btn ghost small"
              disabled={busy || note === (order.admin_note || '')}
              onClick={() => patch({ admin_note: note }, 'Нотатку збережено')}
            >
              Зберегти нотатку
            </button>
          </div>

          <div className="card">
            <h2 style={{ marginTop: 0 }}>Замовлення</h2>
            <div className="table-wrap">
              <table>
                <tbody>
                  {order.items.map((i, idx) => (
                    <tr key={idx}>
                      <td>{i.name}</td>
                      <td className="num">× {i.qty}</td>
                      <td className="num">{money(i.price * i.qty)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row-between" style={{ marginTop: 10 }}>
              <span className="faint">Знижка / бонуси</span>
              <span className="num">{money(order.discount)} / {money(order.bonus_used)}</span>
            </div>
            <div className="row-between" style={{ fontWeight: 700, fontSize: 17 }}>
              <span>До сплати</span>
              <span className="num">{money(order.total)}</span>
            </div>
          </div>
        </div>

        <div>
          <div className="card" style={{ marginBottom: 18 }}>
            <h2 style={{ marginTop: 0 }}>Отримувач</h2>

            <Info label="Прізвище, імʼя, по батькові" copy={fullName}>
              {fullName || <span className="faint">не вказано</span>}
            </Info>

            {/* Телефон окремим блоком і великим шрифтом: його читають
                вголос під час дзвінка й переписують у накладну. Одна
                перевернута цифра — і посилка їде не туди. */}
            <Info label="Номер телефону" copy={order.contact_phone}>
              <a className="info-strong" href={`tel:${order.contact_phone}`}>
                {order.contact_phone}
              </a>
            </Info>

            <Info
              label={DELIVERY_METHODS[order.delivery_method] || 'Доставка'}
              copy={[order.delivery_city, order.delivery_address]
                .filter(Boolean).join(', ')}
            >
              {order.delivery_city && <div>{order.delivery_city}</div>}
              <div className="info-strong">{order.delivery_address}</div>
              {/* Коди довідника показуємо лише там, де вони є: у
                  замовленнях, оформлених до появи вибору відділення,
                  їх немає й не буде. Порожній рядок «Код: —» лише
                  збивав би з пантелику того, хто робить накладну. */}
              {order.delivery_warehouse_ref && (
                <div className="info-codes num">
                  {order.delivery_city_ref} / {order.delivery_warehouse_ref}
                </div>
              )}
            </Info>

            {/* Накладна дублюється тут навмисно. Змінюють її внизу, у
                панелі статусу, а дивляться сюди — коли клієнт питає
                «де посилка», лізти по номер в іншу картку незручно. */}
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

            {/* Попередження до того, як менеджер натисне «Відправлено».
                Клієнт, який не відкривав чат із ботом, не отримає ні
                статусу, ні реквізитів — і про це треба знати заздалегідь,
                а не після того, як він не вийшов на звʼязок. */}
            {client.bot_reachable === false && (
              <Info label="Увага">
                Бот не може написати цьому клієнту — він не відкривав чат.
                Статуси й реквізити не дійдуть; пишіть у стрічку замовлення
                нижче або телефонуйте.
              </Info>
            )}

            <Info label="Telegram" copy={client.username ? `@${client.username}` : ''}>
              {client.username
                ? `@${client.username}`
                : <span className="faint">без імені користувача</span>}
            </Info>

            {order.comment && (
              <Info label="Коментар покупця">{order.comment}</Info>
            )}
          </div>

          <Chat orderId={id} messages={messages} onSent={load} />
        </div>
      </div>

      {askTracking && (
        <TrackingModal
          initial={tracking}
          onCancel={() => setAskTracking(false)}
          onConfirm={confirmShipping}
        />
      )}
    </>
  )
}
