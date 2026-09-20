import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api, authorizedFetch } from '../api'
import { ErrorBar, Field, Info, Loading, Modal, money, useToast } from '../components/ui'
import { STATUS_LABELS, allowedFrom } from '../components/StatusRail'
import {
  OrderStatusBadge, SalesDriveStatusProgress, SalesDriveStatusSelect, isNewOrderStatus, isShippedOrLaterCrmStatus,
} from '../components/OrderStatus'
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

function sameMessages(left, right) {
  if (left === right) return true
  if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) return false
  return left.every((message, index) => {
    const other = right[index]
    return other
      && message.id === other.id
      && message.is_read === other.is_read
      && message.direction === other.direction
      && message.author === other.author
      && message.text === other.text
      && message.file_kind === other.file_kind
      && message.file_name === other.file_name
      && message.created_at === other.created_at
  })
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
    authorizedFetch(api.orders.fileUrl(orderId, message.id))
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
  const busyRef = useRef(false)

  const confirm = async () => {
    if (busyRef.current || !value.trim()) return
    busyRef.current = true
    setBusy(true)
    try {
      await onConfirm(value.trim())
    } finally {
      busyRef.current = false
      setBusy(false)
    }
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

function Chat({ orderId, messages, newMessageIds, onSent }) {
  const notify = useToast()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const sendingRef = useRef(false)
  const logRef = useRef(null)
  const stickToBottomRef = useRef(true)
  const initializedRef = useRef(false)
  const newIds = newMessageIds || new Set()
  const firstNewIndex = messages.findIndex((message) => newIds.has(message.id))
  const newCount = messages.reduce((count, message) => (
    count + (message.direction === 'in' && newIds.has(message.id) ? 1 : 0)
  ), 0)
  const lastMessageId = messages.length ? messages[messages.length - 1].id : 0

  useEffect(() => {
    const node = logRef.current
    if (!node) return
    if (!initializedRef.current) {
      initializedRef.current = true
      node.scrollTop = node.scrollHeight
      stickToBottomRef.current = true
      return
    }
    // Фонове оновлення не повинно виривати менеджера з місця, де він
    // читає стару переписку. Автоскрол — лише якщо він уже був унизу.
    if (stickToBottomRef.current) node.scrollTop = node.scrollHeight
  }, [lastMessageId])

  const send = async () => {
    const body = text.trim()
    if (!body || sendingRef.current) return
    sendingRef.current = true
    setBusy(true)
    try {
      const result = await api.orders.sendMessage(orderId, body)
      setText('')
      // Клієнт міг заблокувати бота — повідомлення збережеться, але не дійде
      if (!result.delivered) notify(result.warning || 'Не доставлено клієнту', 'bad')
      stickToBottomRef.current = true
      onSent(result.message)
      requestAnimationFrame(() => {
        const node = logRef.current
        if (node) node.scrollTop = node.scrollHeight
      })
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      sendingRef.current = false
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
    <div className={`card order-chat-card${newCount > 0 ? ' has-new-messages' : ''}`} id="chat">
      <div className="order-chat-head">
        <div>
          <h2>Листування</h2>
          <div className="faint">Повідомлення клієнта з Telegram і відповіді менеджера</div>
        </div>
        {newCount > 0 && (
          <span className="chat-new-counter">
            <span className="chat-new-counter-dot" aria-hidden="true" />
            {newCount} {newCount === 1 ? 'нове' : 'нових'}
          </span>
        )}
      </div>

      <div
        className="chat-log"
        ref={logRef}
        onScroll={(event) => {
          const node = event.currentTarget
          stickToBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80
        }}
      >
        {messages.length === 0 ? (
          <p className="faint" style={{ margin: 0 }}>
            Повідомлень ще немає. Клієнт отримає ваше в чаті з ботом і зможе
            відповісти прямо звідти.
          </p>
        ) : (
          messages.map((m, index) => {
            const isNewMessage = m.direction === 'in' && newIds.has(m.id)
            return (
              <div key={m.id} className="chat-message-group">
                {index === firstNewIndex && (
                  <div className="new-messages-divider" role="separator" aria-label="Нові повідомлення">
                    <span>Нові повідомлення</span>
                  </div>
                )}
                <div className={`bubble ${m.direction === 'out' ? 'mine' : ''}${isNewMessage ? ' is-new' : ''}`}>
                  <div className="bubble-head faint">
                    <span>
                      {m.direction === 'out' ? m.author || 'Менеджер' : m.author || 'Клієнт'}
                      {' · '}
                      {timestamp(m.created_at)}
                    </span>
                    {isNewMessage && (
                      <span className="bubble-new-badge">
                        <span aria-hidden="true" />
                        Нове
                      </span>
                    )}
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
              </div>
            )
          })
        )}
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
  const workingRef = useRef(false)

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
    if (workingRef.current) return
    workingRef.current = true
    setWorking(true)
    try {
      const fresh = await action()
      onChanged(fresh)
      notify(okText)
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      workingRef.current = false
      setWorking(false)
    }
  }

  const printLabel = async () => {
    if (workingRef.current) return
    workingRef.current = true
    // Вікно треба створити прямо в click-handler. Якщо викликати window.open
    // уже після await fetch, Safari/Chrome можуть вважати це popup і
    // заблокувати — кнопка «Маркування» тоді ніби нічого не робить.
    const preview = window.open('', '_blank')
    if (preview) preview.opener = null
    setWorking(true)
    try {
      const response = await authorizedFetch(api.orders.waybillLabelUrl(order.id), {}, 60000)
      if (!response.ok) {
        let detail = 'Не вдалося отримати маркування'
        try { detail = (await response.json()).detail || detail } catch { /* не JSON */ }
        throw new Error(detail)
      }
      const url = URL.createObjectURL(await response.blob())
      if (preview) {
        preview.location.href = url
      } else {
        const link = document.createElement('a')
        link.href = url
        link.target = '_blank'
        link.rel = 'noopener'
        document.body.appendChild(link)
        link.click()
        link.remove()
      }
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (err) {
      preview?.close()
      notify(err.message, 'bad')
    } finally {
      setWorking(false)
    }
  }

  const crm = CRM_STATE[order.crm_state]
  const disabled = busy || working
  const crmNp = order.crm_snapshot?.novaposhta || {}
  const crmUp = order.crm_snapshot?.ukrposhta || {}
  const localTracking = String(order.tracking_number || '').trim()
  const npTracking = String(crmNp.ttn || '').trim()
  const upTracking = String(crmUp.ttn || '').trim()
  const crmCarrier = npTracking && npTracking === localTracking
    ? 'Нова пошта'
    : upTracking && upTracking === localTracking
      ? 'Укрпошта'
      : ''
  const crmWaybill = order.waybill_source === 'salesdrive'
  const crmManual = crmCarrier === 'Нова пошта' ? crmNp.manual : crmUp.manual
  const crmDeliveryStatusRaw = crmCarrier === 'Нова пошта' ? crmNp.status : crmUp.status
  const crmDeliveryStatusCode = crmCarrier === 'Нова пошта' ? crmNp.statusCode : crmUp.statusCode
  const crmDeliveryStatus = crmDeliveryStatusRaw || (crmDeliveryStatusCode !== null && crmDeliveryStatusCode !== undefined && crmDeliveryStatusCode !== ''
    ? `Статус перевізника · код ${crmDeliveryStatusCode}`
    : '')
  const crmDeliveryUpdated = crmCarrier === 'Нова пошта' ? crmNp.dateStatusUpdate : crmUp.dateStatusUpdate
  const sourceLabel = crmWaybill
    ? crmManual === 0 || crmManual === '0'
      ? 'сформована в SalesDrive'
      : crmManual === 1 || crmManual === '1'
        ? 'внесена вручну в SalesDrive'
        : 'отримана з SalesDrive'
    : WAYBILL_SOURCE[order.waybill_source] || 'без джерела'
  // Не вгадуємо перевізника за самим номером. Для локально створеної
  // накладної джерело однозначно Нова пошта; для CRM-пов'язаної даємо
  // посилання лише коли snapshot прямо підтверджує Nova Poshta.
  const npTrackingUrl = localTracking && (order.waybill_source === 'novaposhta' || crmCarrier === 'Нова пошта')
    ? `https://novaposhta.ua/tracking/?cargo_number=${encodeURIComponent(localTracking)}`
    : ''

  return (
    <div className="waybill-panel">
      {order.tracking_number ? (
        <div className={`waybill-current${crmWaybill ? ' from-crm' : ''}`}>
          <div className="waybill-current-main">
            <div className="waybill-current-title">
              <span className="waybill-carrier-icon" aria-hidden="true">{crmCarrier === 'Укрпошта' ? '✉️' : '📦'}</span>
              <div>
                <div className="faint">{crmCarrier || 'Накладна перевізника'}</div>
                <div className="num info-strong waybill-number">{order.tracking_number}</div>
              </div>
            </div>
            <div className="waybill-meta-row">
              <span className={`chip${crmWaybill ? ' crm-waybill-chip' : ''}`}>ТТН {sourceLabel}</span>
              {order.waybill_ref && <span className="chip ok">Ref отримано</span>}
              {order.waybill_cost ? <span className="chip">Доставка {Number(order.waybill_cost).toLocaleString('uk-UA', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} грн</span> : null}
            </div>
            {crmDeliveryStatus && (
              <div className="waybill-crm-status">
                <span className="waybill-status-dot" aria-hidden="true" />
                <div>
                  <strong>{crmDeliveryStatus}</strong>
                  {crmDeliveryUpdated && <small>Оновлено в CRM: {crmDate(crmDeliveryUpdated)}</small>}
                </div>
              </div>
            )}
          </div>
          <div className="row waybill-actions">
            {npTrackingUrl && (
              <a className="btn ghost small" href={npTrackingUrl} target="_blank" rel="noreferrer">
                Відстежити
              </a>
            )}
            {order.waybill_source === 'novaposhta' && (
              <>
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
              </>
            )}
          </div>
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


const CRM_DELIVERY = {
  Warehouse: 'У відділення Нової пошти',
  WarehouseWarehouse: 'У відділення Нової пошти',
  WarehouseDoors: 'Адресна доставка курʼєром Нової пошти',
  DoorsDoors: 'Курʼєром від адреси до адреси',
  DoorsWarehouse: 'До відділення від адреси',
}

const CRM_NP_PARTY = { Recipient: 'Одержувач', Sender: 'Відправник' }
const CRM_NP_PAYMENT = { Cash: 'Готівка', NonCash: 'Безготівково' }
const CRM_NP_CARGO = {
  Parcel: 'Посилка', Cargo: 'Вантаж', Documents: 'Документи',
  TiresWheels: 'Шини / диски', Pallet: 'Палета',
}
const CRM_NP_BACK = { Money: 'Післяплата', PaymentControl: 'Контроль оплати', None: 'Без післяплати' }

function crmAmount(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return String(value)
  return `${number.toLocaleString('uk-UA', { maximumFractionDigits: 2 })} ₴`
}

function crmDate(value) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return parsed.toLocaleString('uk-UA', {
    day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function resolvedCrmOption(label, raw) {
  const text = String(label || '').trim()
  const source = String(raw || '').trim()
  if (!text && !source) return '—'
  if ((!text || text === source) && /^\d+$/.test(source)) return `ID ${source} · назву не знайдено`
  return text || source
}

function CrmMetric({ label, value, strong = false, tone = '' }) {
  return (
    <div className={`crm-metric ${tone}`}>
      <span>{label}</span>
      <strong className={strong ? 'crm-metric-main' : ''}>{value}</strong>
    </div>
  )
}

function toDmy(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  if (/^\d{2}\.\d{2}\.\d{4}$/.test(raw)) return raw
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
  return match ? `${match[3]}.${match[2]}.${match[1]}` : raw
}

function crmCarrierFromSnapshot(snap) {
  if (snap?.novaposhta?.ttn) return 'novaposhta'
  if (snap?.ukrposhta?.ttn) return 'ukrposhta'
  const provider = String(snap?.deliveryData?.provider || '').trim().toLowerCase()
  return ['novaposhta', 'ukrposhta', 'meest', 'rozetka_delivery'].includes(provider) ? provider : 'novaposhta'
}

function crmEditInitial(order) {
  const snap = order?.crm_snapshot || {}
  const contact = snap.contact || {}
  const counterparty = contact.counterparty || {}
  const ttn = snap?.novaposhta?.ttn || snap?.ukrposhta?.ttn || snap?.deliveryData?.trackingNumber || order?.tracking_number || ''
  return {
    manager_id: snap.managerId ? String(snap.managerId) : '',
    payment_date: toDmy(snap.paymentDate),
    rejection_reason_id: snap.rejectionReasonId ? String(snap.rejectionReasonId) : '',
    comment: snap.comment || '',
    payment_method: snap.paymentMethodRaw || '',
    shipping_method: snap.shippingMethodRaw || '',
    l_name: contact.lName || '',
    f_name: contact.fName || '',
    m_name: contact.mName || '',
    phone: contact.phone || '',
    email: contact.email || '',
    company: contact.company || '',
    date_of_birth: toDmy(contact.dateOfBirth),
    counterparty_name: counterparty.name || '',
    counterparty_code: counterparty.code || '',
    carrier: crmCarrierFromSnapshot(snap),
    tracking_number: ttn,
  }
}

function CrmEditPanel({ order, onSave }) {
  const snap = order?.crm_snapshot || {}
  const options = snap.writeOptions || {}
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState(() => crmEditInitial(order))
  const initialRef = useRef(crmEditInitial(order))

  useEffect(() => {
    const next = crmEditInitial(order)
    initialRef.current = next
    setForm(next)
  }, [order?.crm_fetched_at, order?.crm_id])

  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }))
  const changed = Object.keys(form).filter((key) => String(form[key] ?? '') !== String(initialRef.current[key] ?? ''))

  const submit = async () => {
    if (!changed.length || busyRef.current) return
    busyRef.current = true
    const payload = {}
    for (const key of changed) {
      const value = form[key]
      if (key === 'manager_id' || key === 'rejection_reason_id') {
        if (String(value).trim()) payload[key] = Number(value)
        continue
      }
      payload[key] = value
    }
    // SalesDrive вимагає carrier + tracking_number парою. Якщо менеджер
    // змінив лише номер або лише службу, передаємо і друге актуальне поле.
    if (changed.includes('tracking_number') || changed.includes('carrier')) {
      payload.carrier = form.carrier
      payload.tracking_number = form.tracking_number
    }
    setBusy(true)
    try {
      const fresh = await onSave(payload)
      const next = crmEditInitial(fresh || order)
      initialRef.current = next
      setForm(next)
      setOpen(false)
    } catch {
      // Повідомлення про помилку показує батьківський екран через toast.
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  const managers = Array.isArray(options.managers) ? options.managers : []
  const rejectionReasons = Array.isArray(options.rejectionReasons) ? options.rejectionReasons : []
  const paymentMethods = Array.isArray(options.paymentMethods) ? options.paymentMethods : []
  const shippingMethods = Array.isArray(options.shippingMethods) ? options.shippingMethods : []

  return (
    <details className="crm-editor" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <span>Редагувати дані SalesDrive</span>
        <small>Змінюються тільки вибрані поля; адреса Нової Пошти/Укрпошти тут не редагується</small>
      </summary>
      <div className="crm-editor-body">
        <div className="crm-editor-section">
          <h4>Обробка заявки</h4>
          <div className="crm-editor-grid">
            <Field label="Менеджер CRM">
              {managers.length ? (
                <select className="input" value={form.manager_id} onChange={(e) => set('manager_id', e.target.value)}>
                  {!form.manager_id && <option value="">Не призначено</option>}
                  {form.manager_id && !managers.some((item) => String(item.value) === String(form.manager_id)) && (
                    <option value={form.manager_id}>Поточний менеджер · ID {form.manager_id}</option>
                  )}
                  {managers.map((item) => <option key={item.value} value={item.value}>{item.name}</option>)}
                </select>
              ) : (
                <input className="input" inputMode="numeric" value={form.manager_id} onChange={(e) => set('manager_id', e.target.value.replace(/\D/g, ''))} placeholder="SalesDrive manager ID" />
              )}
            </Field>
            <Field label="Дата оплати" hint="ДД.ММ.РРРР">
              <input className="input" value={form.payment_date} onChange={(e) => set('payment_date', e.target.value)} placeholder="25.08.2025" />
            </Field>
            <Field label="Причина відмови">
              {rejectionReasons.length ? (
                <select className="input" value={form.rejection_reason_id} onChange={(e) => set('rejection_reason_id', e.target.value)}>
                  {!form.rejection_reason_id && <option value="">Не вибрано</option>}
                  {form.rejection_reason_id && !rejectionReasons.some((item) => String(item.value) === String(form.rejection_reason_id)) && (
                    <option value={form.rejection_reason_id}>Поточна причина · ID {form.rejection_reason_id}</option>
                  )}
                  {rejectionReasons.map((item) => <option key={item.value} value={item.value}>{item.name}</option>)}
                </select>
              ) : (
                <input className="input" inputMode="numeric" value={form.rejection_reason_id} onChange={(e) => set('rejection_reason_id', e.target.value.replace(/\D/g, ''))} placeholder="ID причини" />
              )}
            </Field>
            {paymentMethods.length > 0 && (
              <Field label="Спосіб оплати CRM">
                <select className="input" value={form.payment_method} onChange={(e) => set('payment_method', e.target.value)}>
                  {form.payment_method && !paymentMethods.some((item) => String(item.value) === String(form.payment_method)) && (
                    <option value={form.payment_method}>Поточне значення · {form.payment_method}</option>
                  )}
                  {paymentMethods.map((item) => <option key={item.value} value={item.value}>{item.name}</option>)}
                </select>
              </Field>
            )}
            {shippingMethods.length > 0 && (
              <Field label="Спосіб доставки CRM" hint="Місто/відділення/адреса не змінюються цим API">
                <select className="input" value={form.shipping_method} onChange={(e) => set('shipping_method', e.target.value)}>
                  {form.shipping_method && !shippingMethods.some((item) => String(item.value) === String(form.shipping_method)) && (
                    <option value={form.shipping_method}>Поточне значення · {form.shipping_method}</option>
                  )}
                  {shippingMethods.map((item) => <option key={item.value} value={item.value}>{item.name}</option>)}
                </select>
              </Field>
            )}
          </div>
          <Field label="Коментар CRM">
            <textarea className="input" rows={3} value={form.comment} onChange={(e) => set('comment', e.target.value)} />
          </Field>
        </div>

        <div className="crm-editor-section">
          <h4>Контакт у CRM</h4>
          <div className="crm-editor-grid">
            <Field label="Прізвище"><input className="input" value={form.l_name} onChange={(e) => set('l_name', e.target.value)} /></Field>
            <Field label="Імʼя"><input className="input" value={form.f_name} onChange={(e) => set('f_name', e.target.value)} /></Field>
            <Field label="По батькові"><input className="input" value={form.m_name} onChange={(e) => set('m_name', e.target.value)} /></Field>
            <Field label="Телефон"><input className="input" value={form.phone} onChange={(e) => set('phone', e.target.value)} /></Field>
            <Field label="Email"><input className="input" value={form.email} onChange={(e) => set('email', e.target.value)} /></Field>
            <Field label="Компанія"><input className="input" value={form.company} onChange={(e) => set('company', e.target.value)} /></Field>
            <Field label="Дата народження" hint="ДД.ММ.РРРР"><input className="input" value={form.date_of_birth} onChange={(e) => set('date_of_birth', e.target.value)} /></Field>
            <Field label="Контрагент"><input className="input" value={form.counterparty_name} onChange={(e) => set('counterparty_name', e.target.value)} /></Field>
            <Field label="Код контрагента"><input className="input" value={form.counterparty_code} onChange={(e) => set('counterparty_code', e.target.value)} /></Field>
          </div>
        </div>

        <div className="crm-editor-section">
          <h4>ТТН у SalesDrive</h4>
          <div className="crm-editor-grid crm-editor-tracking">
            <Field label="Перевізник">
              <select
                className="input"
                value={form.carrier}
                disabled={Boolean(initialRef.current.tracking_number)}
                onChange={(e) => set('carrier', e.target.value)}
              >
                <option value="novaposhta">Нова Пошта</option>
                <option value="ukrposhta">Укрпошта</option>
                <option value="meest">Meest</option>
                <option value="rozetka_delivery">Rozetka Delivery</option>
              </select>
            </Field>
            <Field label="ТТН">
              <input className="input num" value={form.tracking_number} onChange={(e) => set('tracking_number', e.target.value.trim())} placeholder="Номер накладної" />
            </Field>
          </div>
          <p className="faint crm-editor-warning">
            Місто, відділення та адресу Нової Пошти/Укрпошти цей endpoint SalesDrive не дозволяє змінювати. Панель їх лише читає з CRM.
            {initialRef.current.tracking_number ? ' Для вже створеної ТТН перевізник зафіксований: змінюється тільки номер у тому самому carrier-блоці.' : ''}
          </p>
        </div>

        <div className="crm-editor-actions">
          <span className="faint">{changed.length ? `Змінено полів: ${changed.length}` : 'Немає незбережених змін'}</span>
          <button className="btn" disabled={busy || !changed.length} onClick={submit}>
            {busy ? 'Зберігаємо в CRM…' : 'Зберегти в SalesDrive'}
          </button>
        </div>
      </div>
    </details>
  )
}

function CrmSnapshotPanel({ order, crmStatuses, refreshing, onRefresh, onUpdate }) {
  const snap = order.crm_snapshot
  const contact = snap?.contact || {}
  const np = snap?.novaposhta || {}
  const up = snap?.ukrposhta || {}
  const utm = snap?.utm || {}
  const deliveryData = snap?.deliveryData || {}
  const deliveryItems = Array.isArray(deliveryData.items) ? deliveryData.items : []
  const products = Array.isArray(snap?.products) ? snap.products : []
  const ttn = np.ttn || up.ttn || deliveryData.trackingNumber || ''
  const deliveryStatus = np.status || up.status || ''
  const deliveryStatusCode = np.statusCode ?? up.statusCode
  const deliveryStatusLabel = deliveryStatus || (deliveryStatusCode !== null && deliveryStatusCode !== undefined && deliveryStatusCode !== ''
    ? `Код статусу ${deliveryStatusCode}`
    : '')
  const deliveryCost = np.cost ?? up.cost ?? snap?.shippingCosts
  const deliveryCode = np.delivery || up.delivery || deliveryData.type || ''
  const total = Number(snap?.paymentAmount)
  const crmPaidNumber = Number(snap?.payedAmount)
  const crmRestNumber = Number(snap?.restPay)
  const crmPaymentText = `${snap?.paymentMethod || ''} ${snap?.paymentMethodRaw || ''}`.trim().toLocaleLowerCase('uk-UA')
  const cardPayment = order.payment_method === 'card' || crmPaymentText.includes('карт')
  const cardShippedOrLater = cardPayment && isShippedOrLaterCrmStatus(order, crmStatuses)
  const crmAlreadyFullyPaid = Number.isFinite(total) && total > 0
    && Number.isFinite(crmPaidNumber) && crmPaidNumber >= total
    && (!Number.isFinite(crmRestNumber) || crmRestNumber <= 0)
  const calculatedCardPayment = cardShippedOrLater && Number.isFinite(total) && total > 0 && !crmAlreadyFullyPaid
  const paid = cardShippedOrLater && Number.isFinite(total) && total > 0 ? total : snap?.payedAmount
  const rest = cardShippedOrLater && Number.isFinite(total) && total > 0 ? 0 : snap?.restPay
  const paidNumber = Number(paid)
  const progress = Number.isFinite(total) && total > 0 && Number.isFinite(paidNumber)
    ? Math.max(0, Math.min(100, Math.round((paidNumber / total) * 100)))
    : null
  const customerName = [contact.lName, contact.fName, contact.mName].filter(Boolean).join(' ')
  const hasFinanceDetails = [snap?.commissionAmount, snap?.costPriceAmount, snap?.expensesAmount, snap?.profitAmount]
    .some((value) => value !== null && value !== undefined && value !== '')
  const hasSource = [utm.source, utm.medium, utm.campaign, utm.page, utm.sourceFull].some(Boolean)
  const managerLabel = snap?.managerName || (snap?.managerId ? `ID ${snap.managerId}` : 'Не призначено')
  const snapshotSource = snap?.source === 'webhook' ? 'Webhook' : 'API'
  const paymentLabel = resolvedCrmOption(snap?.paymentMethod, snap?.paymentMethodRaw)
  const shippingLabel = resolvedCrmOption(snap?.shippingMethod, snap?.shippingMethodRaw)
  const paymentUnresolved = /^ID \d+/.test(paymentLabel)
  const shippingUnresolved = /^ID \d+/.test(shippingLabel)
  const crmAddress = snap?.shippingAddress
    || [np.cityName || np.city, np.address || [np.streetName || np.street, np.house, np.flat].filter(Boolean).join(', ')].filter(Boolean).join(', ')
    || [up.cityName || up.city, up.branchName || up.branch, up.streetName || up.street, up.house, up.flat].filter(Boolean).join(', ')
  const localDestination = [order.delivery_city, order.delivery_address].filter(Boolean).join(', ')
  const cargoLabel = CRM_NP_CARGO[np.cargoType || deliveryData.cargoType] || np.cargoType || deliveryData.cargoType || ''
  const deliveryPaymentLabel = CRM_NP_PAYMENT[np.paymentMethod || deliveryData.paymentMethod] || np.paymentMethod || deliveryData.paymentMethod || ''
  const postpayPayerLabel = CRM_NP_PARTY[np.postpayPayer || deliveryData.postpayPayer] || np.postpayPayer || deliveryData.postpayPayer || ''
  const deliveryPayerLabel = CRM_NP_PARTY[np.payer] || np.payer || ''
  const backDeliveryLabel = CRM_NP_BACK[np.backDelivery] || np.backDelivery || ''

  return (
    <section className="crm-live-card crm-live-card-v2" aria-label="Актуальні дані SalesDrive">
      <div className="crm-live-head">
        <div>
          <div className="order-payment-kicker">SalesDrive · заявка {order.crm_id}</div>
          <div className="crm-live-title-row">
            <OrderStatusBadge order={order} crmStatuses={crmStatuses} compact />
            <span className={`crm-source-chip ${snapshotSource === 'Webhook' ? 'webhook' : ''}`}>{snapshotSource}</span>
          </div>
          <div className="faint">
            {order.crm_fetched_at ? `Дані CRM оновлено: ${timestamp(order.crm_fetched_at)}` : 'Ще не отримували актуальний стан заявки'}
          </div>
        </div>
        <button className="btn ghost small" disabled={refreshing} onClick={onRefresh}>
          {refreshing ? 'Оновлення…' : 'Оновити з CRM'}
        </button>
      </div>

      {!snap ? (
        <div className="crm-empty-snapshot">
          Дані заявки ще не завантажені. Натисніть «Оновити з CRM».
        </div>
      ) : (
        <>
          <div className="crm-primary-grid">
            <div className="crm-primary-card">
              <span className="crm-primary-icon" aria-hidden="true">💳</span>
              <div>
                <span className="crm-primary-label">Спосіб оплати</span>
                <strong className={paymentUnresolved ? 'crm-unresolved' : ''}>{paymentLabel}</strong>
                <small>{calculatedCardPayment
                  ? `Розрахунково оплачено ${crmAmount(paid)} · залишок ${crmAmount(rest)}`
                  : snap.paymentDate
                    ? `Продаж/оплата: ${crmDate(snap.paymentDate)}`
                    : `${crmAmount(paid)} оплачено · ${crmAmount(rest)} залишок`}
                </small>
              </div>
            </div>
            <div className="crm-primary-card">
              <span className="crm-primary-icon" aria-hidden="true">📦</span>
              <div>
                <span className="crm-primary-label">Спосіб доставки</span>
                <strong className={shippingUnresolved ? 'crm-unresolved' : ''}>{shippingLabel}</strong>
                <small>{CRM_DELIVERY[deliveryCode] || deliveryStatusLabel || crmAddress || localDestination || 'Деталі служби доставки ще не заповнені'}</small>
              </div>
            </div>
            <div className="crm-primary-card">
              <span className="crm-primary-icon" aria-hidden="true">👤</span>
              <div>
                <span className="crm-primary-label">Відповідальний менеджер</span>
                <strong>{managerLabel}</strong>
                <small>{snap.managerId ? `SalesDrive ID ${snap.managerId}` : 'У CRM менеджера ще не призначено'}</small>
              </div>
            </div>
          </div>

          <div className="crm-data-strip">
            <span><b>CRM ID</b> {snap.id || order.crm_id}</span>
            {snap.version !== null && snap.version !== undefined && <span><b>Версія</b> {snap.version}</span>}
            <span><b>Джерело</b> {snapshotSource}</span>
            {(paymentUnresolved || shippingUnresolved) && (
              <span className="crm-data-warning"><b>Увага</b> довідник CRM не розвʼязав назву однієї з опцій</span>
            )}
          </div>

          <div className="crm-section">
            <div className="crm-section-head">
              <div>
                <h3>Розрахунки</h3>
                <p>{calculatedCardPayment ? 'CRM-суми з розрахунковим правилом карткової оплати' : 'Фактичні суми із заявки SalesDrive'}</p>
              </div>
              <div className="crm-payment-head-meta">
                {calculatedCardPayment && (
                  <span
                    className="crm-finance-rule-chip"
                    title="Карткова оплата вважається отриманою, коли статус SalesDrive — «Відправлений» або наступний етап. Дані платежу в CRM не переписуються."
                  >
                    ✓ Розрахунково оплачено
                  </span>
                )}
                {progress !== null && <span className={`crm-payment-progress-label ${progress >= 100 ? 'done' : ''}`}>{progress}% оплачено</span>}
              </div>
            </div>
            {progress !== null && (
              <div className="crm-payment-progress" aria-label={`Оплачено ${progress}%`}>
                <span style={{ width: `${progress}%` }} />
              </div>
            )}
            <div className="crm-metrics-grid">
              <CrmMetric label="Сума CRM" value={crmAmount(snap.paymentAmount)} strong />
              <CrmMetric label={calculatedCardPayment ? 'Оплачено · розрахунок' : 'Оплачено'} value={crmAmount(paid)} tone={Number(paid) > 0 ? 'ok' : ''} />
              <CrmMetric label="Залишок" value={crmAmount(rest)} tone={Number(rest) > 0 ? 'warn' : 'ok'} />
              {deliveryCost !== null && deliveryCost !== undefined && deliveryCost !== '' && (
                <CrmMetric label="Вартість доставки" value={crmAmount(deliveryCost)} />
              )}
            </div>
            {hasFinanceDetails && (
              <div className="crm-secondary-metrics">
                <CrmMetric label="Собівартість" value={crmAmount(snap.costPriceAmount)} />
                <CrmMetric label="Комісія" value={crmAmount(snap.commissionAmount)} />
                <CrmMetric label="Витрати" value={crmAmount(snap.expensesAmount)} />
                <CrmMetric label="Прибуток" value={crmAmount(snap.profitAmount)} tone="ok" />
              </div>
            )}
          </div>

          <div className="crm-two-columns">
            <div className="crm-section">
              <div className="crm-section-head compact"><div><h3>Одержувач</h3><p>Контакт, який зараз записаний у CRM</p></div></div>
              <div className="crm-detail-list">
                <div><span>ПІБ</span><strong>{customerName || '—'}</strong></div>
                <div><span>Телефон</span><strong>{contact.phone || '—'}</strong></div>
                {contact.email && <div><span>Email</span><strong>{contact.email}</strong></div>}
                {contact.company && <div><span>Компанія</span><strong>{contact.company}</strong></div>}
                {contact.counterparty?.name && <div><span>Контрагент</span><strong>{contact.counterparty.name}{contact.counterparty.code ? ` · ${contact.counterparty.code}` : ''}</strong></div>}
                {contact.leadsCount !== null && contact.leadsCount !== undefined && <div><span>Заявок клієнта</span><strong>{contact.leadsCount}</strong></div>}
                {contact.leadsSalesCount !== null && contact.leadsSalesCount !== undefined && <div><span>Успішних продажів</span><strong>{contact.leadsSalesCount}</strong></div>}
                {contact.leadsSalesAmount !== null && contact.leadsSalesAmount !== undefined && <div><span>Сума продажів</span><strong>{crmAmount(contact.leadsSalesAmount)}</strong></div>}
                {contact.userId && <div><span>Менеджер контакту</span><strong>ID {contact.userId}</strong></div>}
              </div>
            </div>

            <div className="crm-section">
              <div className="crm-section-head compact"><div><h3>Доставка</h3><p>ТТН і стан перевізника із SalesDrive</p></div></div>
              <div className="crm-detail-list">
                <div><span>Тип</span><strong>{CRM_DELIVERY[deliveryCode] || shippingLabel}</strong></div>
                <div><span>Перевізник</span><strong>{np.provider === 'novaposhta' ? 'Нова пошта' : up.provider === 'ukrposhta' ? 'Укрпошта' : deliveryData.provider || shippingLabel}</strong></div>
                <div><span>ТТН</span><strong>{ttn || 'Ще не створена'}</strong></div>
                {deliveryItems.length > 1 && <div><span>Відправлень у CRM</span><strong>{deliveryItems.length}</strong></div>}
                <div><span>Статус</span><strong>{deliveryStatusLabel || '—'}</strong></div>
                {deliveryCost !== null && deliveryCost !== undefined && deliveryCost !== '' && <div><span>Вартість доставки</span><strong>{crmAmount(deliveryCost)}</strong></div>}
                {(np.ref || up.ref || deliveryData.trackingNumberRef) && <div className="crm-detail-wide"><span>Ref ТТН</span><strong className="crm-break">{np.ref || up.ref || deliveryData.trackingNumberRef}</strong></div>}
                {localDestination && <div className="crm-detail-wide"><span>Адреса з ELFAR</span><strong>{localDestination}</strong></div>}
                {crmAddress && <div className="crm-detail-wide"><span>Адреса/Ref у CRM</span><strong className="crm-break">{crmAddress}</strong></div>}
                {(np.areaName || np.regionName) && <div><span>Область / район</span><strong>{[np.areaName, np.regionName].filter(Boolean).join(' · ')}</strong></div>}
                {np.cityName && <div><span>Місто</span><strong>{[np.cityType, np.cityName].filter(Boolean).join(' ')}</strong></div>}
                {np.branchNumber && <div><span>Відділення</span><strong>№{np.branchNumber}</strong></div>}
                {!np.branchNumber && np.branch && <div className="crm-detail-wide"><span>Ref відділення</span><strong className="crm-break">{np.branch}</strong></div>}
                {np.postpaySum !== null && np.postpaySum !== undefined && np.postpaySum !== '' && <div><span>Післяплата</span><strong>{crmAmount(np.postpaySum)}</strong></div>}
                {cargoLabel && <div><span>Тип вантажу</span><strong>{cargoLabel}</strong></div>}
                {deliveryPayerLabel && <div><span>Платник доставки</span><strong>{deliveryPayerLabel}</strong></div>}
                {deliveryPaymentLabel && <div><span>Оплата доставки</span><strong>{deliveryPaymentLabel}</strong></div>}
                {backDeliveryLabel && <div><span>Зворотна доставка</span><strong>{backDeliveryLabel}</strong></div>}
                {postpayPayerLabel && <div><span>Платник післяплати</span><strong>{postpayPayerLabel}</strong></div>}
                {np.statusCode !== null && np.statusCode !== undefined && np.statusCode !== '' && <div><span>Код статусу НП</span><strong>{String(np.statusCode)}</strong></div>}
                {np.manual !== null && np.manual !== undefined && <div><span>Джерело ТТН</span><strong>{Number(np.manual) === 1 ? 'Введена вручну в CRM' : 'Створена через SalesDrive'}</strong></div>}
                {np.dateStatusUpdate && <div><span>Статус оновлено</span><strong>{crmDate(np.dateStatusUpdate)}</strong></div>}
                {(np.deliveryDateAndTime || up.deliveryDateAndTime) && <div><span>Прибуття</span><strong>{crmDate(np.deliveryDateAndTime || up.deliveryDateAndTime)}</strong></div>}
                {np.recipientDateTime && <div><span>Отримано</span><strong>{crmDate(np.recipientDateTime)}</strong></div>}
              </div>
            </div>
          </div>

          {products.length > 0 && (
            <div className="crm-section">
              <div className="crm-section-head compact"><div><h3>Товари в заявці</h3><p>Позиції читаються з актуального data[].products, без застарілого meta.products.options</p></div></div>
              <div className="crm-products-v2">
                {products.map((product, index) => (
                  <div className="crm-product-row" key={`${product.id || product.productId || product.sku || index}-${index}`}>
                    <div className="crm-product-main">
                      <strong>{product.name || 'Товар'}</strong>
                      <span>{[
                        product.sku ? `SKU ${product.sku}` : '',
                        product.barcode ? `штрихкод ${product.barcode}` : '',
                        product.categoryName || '',
                      ].filter(Boolean).join(' · ')}</span>
                      {(product.description || product.note) && <small>{product.description || product.note}</small>}
                      {(product.manufacturer || product.mass || product.volume) && (
                        <small>{[
                          product.manufacturer ? `Виробник: ${product.manufacturer}` : '',
                          product.mass ? `Вага: ${product.mass}` : '',
                          product.volume ? `Обʼєм: ${product.volume}` : '',
                        ].filter(Boolean).join(' · ')}</small>
                      )}
                      {product.href && <small className="crm-break">CRM URL: {product.href}</small>}
                    </div>
                    <div className="crm-product-numbers">
                      <strong>{product.amount ?? '—'} × {crmAmount(product.price)}</strong>
                      {(product.discount !== null && product.discount !== undefined && product.discount !== '' && Number(product.discount) !== 0) && (
                        <span>Знижка: {product.discount}{Number(product.percentDiscount) === 1 ? '%' : ' ₴'}</span>
                      )}
                      {product.costPrice !== null && product.costPrice !== undefined && product.costPrice !== '' && <span>Собівартість: {crmAmount(product.costPrice)}</span>}
                      {product.restCount !== null && product.restCount !== undefined && <span>Залишок: {product.restCount}</span>}
                      {product.stockId && <span>Склад ID: {product.stockId}</span>}
                      {Array.isArray(product.priceTypes) && product.priceTypes.length > 0 && <span>Додаткових цін: {product.priceTypes.length}</span>}
                      {Array.isArray(product.complect) && product.complect.length > 0 && <span>Складових комплекту: {product.complect.length}</span>}
                      {product.defaultPriceData && <span>Є базова ціна каталогу CRM</span>}
                      {Number(product.upsell) === 1 && <span className="crm-product-chip">Допродаж</span>}
                      {Number(product.isComplect) === 1 && <span className="crm-product-chip">Комплект</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <details className="crm-more">
            <summary>Додаткові дані CRM</summary>
            <div className="crm-two-columns crm-more-body">
              <div className="crm-section inner">
                <div className="crm-detail-list">
                  <div><span>Створено в CRM</span><strong>{crmDate(snap.orderTime)}</strong></div>
                  {snap.externalId && <div><span>External ID</span><strong>{snap.externalId}</strong></div>}
                  {snap.formId !== null && snap.formId !== undefined && <div><span>База / Form ID</span><strong>{String(snap.formId)}</strong></div>}
                  {snap.typeId !== null && snap.typeId !== undefined && <div><span>Тип заявки ID</span><strong>{String(snap.typeId)}</strong></div>}
                  {snap.timeEntryOrder && <div><span>Прийнято</span><strong>{crmDate(snap.timeEntryOrder)}</strong></div>}
                  {snap.holderTime && <div><span>Час обробки</span><strong>{String(snap.holderTime)}</strong></div>}
                  {snap.rejectionReason && <div><span>Причина відмови</span><strong>{String(snap.rejectionReason)}</strong></div>}
                  {snap.comment && <div className="crm-detail-wide"><span>Коментар CRM</span><strong>{snap.comment}</strong></div>}
                </div>
              </div>
              {hasSource && (
                <div className="crm-section inner">
                  <div className="crm-detail-list">
                    {utm.source && <div><span>Джерело</span><strong>{utm.source}</strong></div>}
                    {utm.medium && <div><span>Канал</span><strong>{utm.medium}</strong></div>}
                    {utm.campaign && <div><span>Кампанія</span><strong>{utm.campaign}</strong></div>}
                    {utm.page && <div><span>Сторінка</span><strong>{utm.page}</strong></div>}
                    {utm.sourceFull && <div className="crm-detail-wide"><span>Повне джерело</span><strong className="crm-break">{utm.sourceFull}</strong></div>}
                  </div>
                </div>
              )}
            </div>
          </details>

          <CrmEditPanel order={order} onSave={onUpdate} />
        </>
      )}

      <p className="faint crm-live-note">
        SalesDrive є джерелом цих CRM-даних. Локальний каталог ELFAR і його ціни з read-side snapshot не перезаписуються.
      </p>
    </section>
  )
}

export default function OrderPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const notify = useToast()

  const [order, setOrder] = useState(null)
  const [messages, setMessages] = useState([])
  // Повідомлення, які були непрочитаними в момент, коли менеджер побачив
  // цю картку. На сервері вони одразу стають прочитаними, але локальна
  // мітка живе до виходу зі сторінки — інакше «Нове» зникало б ще до того,
  // як око встигне знайти репліку в довгій історії.
  const [newMessageIds, setNewMessageIds] = useState(() => new Set())
  const [error, setError] = useState('')
  const [tracking, setTracking] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [askTracking, setAskTracking] = useState(false)
  const [crmStatuses, setCrmStatuses] = useState([])
  const [crmRefreshing, setCrmRefreshing] = useState(false)
  const [crmAutoRefreshed, setCrmAutoRefreshed] = useState(false)
  const loadedOrderRef = useRef(null)
  const messagesRef = useRef([])
  const messagePollTickRef = useRef(0)
  const trackingDirtyRef = useRef(false)
  const noteDirtyRef = useRef(false)
  const crmRefreshInFlightRef = useRef(false)
  const mutationInFlightRef = useRef(false)

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const applyFreshOrder = useCallback((fresh) => {
    if (!fresh) return
    setOrder(fresh)
    // Фоновий refresh не має перезаписати текст, який менеджер саме зараз
    // редагує у полі ТТН або нотатки. Серверне значення підтягуємо лише
    // поки відповідна чернетка не змінена локально.
    if (!trackingDirtyRef.current) setTracking(fresh.tracking_number || '')
    if (!noteDirtyRef.current) setNote(fresh.admin_note || '')
  }, [])

  const loadInitial = useCallback(async () => {
    try {
      const [fresh, log] = await Promise.all([
        api.orders.get(id),
        api.orders.messages(id),
      ])
      applyFreshOrder(fresh)
      messagesRef.current = log
      setMessages(log)
      setError('')
      const unseen = log
        .filter((message) => message.direction === 'in' && !message.is_read)
        .map((message) => message.id)
      // Перший вхід у конкретне замовлення задає стартову межу «нових».
      // Подальші load() після зміни статусу/нотатки не повинні її стирати:
      // сервер уже позначив репліки прочитаними, але менеджеру все ще треба
      // бачити, що саме було новим у цій сесії перегляду.
      if (loadedOrderRef.current !== String(id)) {
        loadedOrderRef.current = String(id)
        setNewMessageIds(new Set(unseen))
      } else if (unseen.length > 0) {
        setNewMessageIds((current) => {
          const next = new Set(current)
          unseen.forEach((messageId) => next.add(messageId))
          return next
        })
      }
      if (unseen.length > 0) {
        // Спершу зберегли список непрочитаних для UX, тільки потім гасимо
        // глобальний лічильник. Відповідь цього запиту навмисно не кладе́мо
        // у state, щоб мітки не мигнули й не зникли.
        api.orders.markMessagesRead(id).catch(() => {})
      }
    } catch (err) {
      setError(err.message)
    }
  }, [id, applyFreshOrder])

  useEffect(() => {
    // React Router може перевикористати той самий компонент для іншого id.
    // Скидаємо тільки session-state картки, а не всю сторінку браузера.
    loadedOrderRef.current = null
    trackingDirtyRef.current = false
    noteDirtyRef.current = false
    crmRefreshInFlightRef.current = false
    setOrder(null)
    messagesRef.current = []
    messagePollTickRef.current = 0
    setMessages([])
    setNewMessageIds(new Set())
    setTracking('')
    setNote('')
    setError('')
    setCrmAutoRefreshed(false)
    loadInitial()
  }, [id, loadInitial])

  // Клік по синій мітці «Нове повідомлення» у списку веде одразу до
  // листування. Hash браузер може обробити раніше, ніж React намалює чат,
  // тому після завантаження картки повторюємо scrollIntoView явно.
  useEffect(() => {
    if (!order || window.location.hash !== '#chat') return
    const frame = requestAnimationFrame(() => {
      document.getElementById('chat')?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    })
    return () => cancelAnimationFrame(frame)
  }, [order?.id])

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
    if (!order?.crm_id || crmRefreshInFlightRef.current) return
    crmRefreshInFlightRef.current = true
    if (!quiet) setCrmRefreshing(true)
    try {
      const fresh = await api.orders.salesdriveRefresh(order.id, !quiet)
      applyFreshOrder(fresh)
      if (!quiet) notify('Дані SalesDrive оновлено')
    } catch (err) {
      if (!quiet) notify(err.message, 'bad')
    } finally {
      crmRefreshInFlightRef.current = false
      if (!quiet) setCrmRefreshing(false)
    }
  }, [order?.id, order?.crm_id, notify, applyFreshOrder])

  const updateCrm = useCallback(async (payload) => {
    if (!order?.crm_id) throw new Error('Замовлення не пов’язане із SalesDrive')
    try {
      const fresh = await api.orders.salesdriveUpdate(order.id, payload)
      applyFreshOrder(fresh)
      notify('Дані SalesDrive збережено')
      return fresh
    } catch (err) {
      notify(err.message, 'bad')
      throw err
    }
  }, [order?.id, order?.crm_id, notify, applyFreshOrder])

  useEffect(() => {
    if (order?.crm_id && !crmAutoRefreshed) {
      setCrmAutoRefreshed(true)
      refreshCrm(true)
    }
  }, [order?.crm_id, crmAutoRefreshed, refreshCrm])

  // Поки картка відкрита, періодично перечитуємо саме заявку SalesDrive.
  // Статуси приходять webhook-ом, а повний read-side потрібен для оплат,
  // менеджера й доставки. 5 хв плюс серверний fresh-cache не витрачають
  // документований ліміт /api/order/list/ на кожну відкриту вкладку.
  useVisiblePolling(() => refreshCrm(true), 300000, { enabled: Boolean(order?.crm_id) })
  useVisiblePolling(loadCrmStatuses, 300000, { enabled: Boolean(order?.crm_id) })

  // Webhook змінює локальний рядок замовлення майже миттєво. Цей легкий
  // poll читає тільки нашу БД, без звернення до SalesDrive, і непомітно
  // підтягує статус, ТТН, оплату, нотатку та інші поля у відкриту картку.
  const refreshLocalOrder = useCallback(async () => {
    const fresh = await api.orders.get(id)
    applyFreshOrder(fresh)
  }, [id, applyFreshOrder])
  useVisiblePolling(refreshLocalOrder, 10000)

  // Прийшли зі списку по кнопці «Відпр.» — одразу питаємо накладну
  useEffect(() => {
    if (order && params.get('ship') === '1' && order.status !== 'shipped') {
      setAskTracking(true)
      setParams({}, { replace: true })
    }
  }, [order, params, setParams])

  // Відповідь клієнта приходить у бот, а не в панель. Оновлюємо тільки
  // стрічку повідомлень; решта картки не переходить у loading і не скаче.
  // Якщо історія не змінилась, навіть React-state лишається тим самим.
  const pollMessages = useCallback(async () => {
    messagePollTickRef.current += 1
    // Нові повідомлення треба бачити швидко, але немає сенсу кожні 5 с
    // передавати назад усі 200 реплік. П'ять циклів читаємо лише delta,
    // шостий робимо компактну повну звірку: так оновлюються й ✓✓ read
    // receipts для вже надісланих менеджером повідомлень.
    const reconcile = messagePollTickRef.current % 6 === 0
    const current = messagesRef.current
    const lastId = current.length ? current[current.length - 1]?.id : null
    const fresh = await api.orders.messages(id, false, reconcile ? null : lastId)

    let next = current
    if (reconcile || lastId === null) {
      next = sameMessages(current, fresh) ? current : fresh
    } else if (fresh.length > 0) {
      const byId = new Map(current.map((message) => [message.id, message]))
      fresh.forEach((message) => byId.set(message.id, message))
      next = [...byId.values()].sort((a, b) => Number(a.id) - Number(b.id))
    }

    if (next !== current) {
      messagesRef.current = next
      setMessages(next)
    }

    // Для нових маркерів цікавить лише відповідь поточного запиту: при
    // reconcile старі вже прочитані сервером і не створять дубль.
    const unseen = fresh
      .filter((message) => message.direction === 'in' && !message.is_read)
      .map((message) => message.id)
    if (unseen.length > 0) {
      setNewMessageIds((known) => {
        const nextIds = new Set(known)
        unseen.forEach((messageId) => nextIds.add(messageId))
        return nextIds
      })
      api.orders.markMessagesRead(id).catch(() => {})
    }
  }, [id])
  useVisiblePolling(pollMessages, 5000)

  const appendSentMessage = useCallback((message) => {
    if (!message) return
    setMessages((current) => {
      const index = current.findIndex((item) => item.id === message.id)
      const next = index < 0 ? [...current, message] : current.map((item) => item.id === message.id ? message : item)
      messagesRef.current = next
      return next
    })
  }, [])

  const patch = async (payload, okText) => {
    if (mutationInFlightRef.current) return false
    mutationInFlightRef.current = true
    setBusy(true)
    try {
      const fresh = await api.orders.patch(id, payload)
      if (Object.prototype.hasOwnProperty.call(payload, 'tracking_number')) trackingDirtyRef.current = false
      if (Object.prototype.hasOwnProperty.call(payload, 'admin_note')) noteDirtyRef.current = false
      applyFreshOrder(fresh)
      notify(okText)
      return true
    } catch (err) {
      notify(err.message, 'bad')
      return false
    } finally {
      mutationInFlightRef.current = false
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
    trackingDirtyRef.current = false
    setTracking(value)
    const saved = await patch(
      { status: 'shipped', tracking_number: value },
      'Відправлено, ТТН надіслано клієнту',
    )
    if (saved) setAskTracking(false)
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
  const isNewOrder = isNewOrderStatus(order, crmStatuses)

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
            {isNewOrder && (
              <span className="order-new-order-chip">
                <span aria-hidden="true" />
                Нове замовлення
              </span>
            )}
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

            {order.crm_id && (
              <SalesDriveStatusProgress order={order} statuses={crmStatuses} />
            )}

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
                      applyFreshOrder(fresh)
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
              <CrmSnapshotPanel
                order={order}
                crmStatuses={crmStatuses}
                refreshing={crmRefreshing}
                onRefresh={() => { refreshCrm(false); loadCrmStatuses() }}
                onUpdate={updateCrm}
              />
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

            <WaybillPanel
              order={order}
              busy={busy}
              onChanged={(fresh) => {
                trackingDirtyRef.current = false
                applyFreshOrder(fresh)
              }}
            />

            <Field
              label="Номер накладної"
              hint="Вписати вручну, якщо ТТН створено в кабінеті перевізника чи в SalesDrive. При переході в «Відправлено» надсилається клієнту автоматично"
            >
              <div className="row">
                <input
                  className="input"
                  value={tracking}
                  onChange={(e) => {
                    trackingDirtyRef.current = true
                    setTracking(e.target.value)
                  }}
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
                onChange={(e) => {
                  noteDirtyRef.current = true
                  setNote(e.target.value)
                }}
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

          <Chat orderId={id} messages={messages} newMessageIds={newMessageIds} onSent={appendSentMessage} />
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
