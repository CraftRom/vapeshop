import { STATUS_LABELS } from './StatusRail'
import {
  crmBusinessOutcomeName, crmStatusAllowsCalculatedCardPayment,
} from '../crmStatus'

export { crmBusinessOutcomeName, normalizeCrmStatusName } from '../crmStatus'

/**
 * Бізнес-ознака «нового» замовлення без прив'язки до ID статусу SalesDrive.
 * ID статусів у CRM налаштовувані, тому порівнюємо семантичні назви.
 */
export function isNewStatusName(value) {
  const name = String(value || '').trim().toLocaleLowerCase('uk-UA')
  return ['новий', 'нове', 'new'].includes(name)
}

/** Один display-model статусу для всієї панелі. */
export function orderDisplayStatus(order, crmStatuses = []) {
  if (!order) return { source: 'legacy', id: '', name: '—', isCrm: false }

  if (order.crm_id) {
    const id = String(order.crm_status_id || order.crm_snapshot?.statusId || '').trim()
    const fromDictionary = crmStatuses.find((item) => String(item.id) === id)?.name
    const name = String(
      fromDictionary
      || order.crm_status_name
      || order.crm_snapshot?.statusName
      || (id ? `Статус CRM #${id}` : 'Очікує статус із CRM'),
    ).trim()
    return { source: 'crm', id, name, isCrm: true }
  }

  const id = String(order.status || '').trim()
  return {
    source: 'legacy', id, name: STATUS_LABELS[id] || id || '—', isCrm: false,
  }
}

export function isNewOrderStatus(order, crmStatuses = []) {
  if (!order) return false
  const status = orderDisplayStatus(order, crmStatuses)
  return status.isCrm ? isNewStatusName(status.name) : status.id === 'new'
}

export function crmBusinessOutcome(order, statuses = []) {
  const current = orderDisplayStatus(order, statuses)
  return current.isCrm ? crmBusinessOutcomeName(current.name) : 'pending'
}

export function isNegativeCrmOutcome(order, statuses = []) {
  return crmBusinessOutcome(order, statuses) === 'refusal'
}

/**
 * Правило розрахункової карткової оплати.
 *
 * Раніше UI вважав будь-який статус, розташований у довіднику ПІСЛЯ
 * «Відправлений», таким що «пройшов відправку». Це помилково: довідник
 * SalesDrive — список можливих статусів, а не журнал переходів. Через це
 * «Відмова», «Повернення» та «Видалений» штучно ставали 100% оплаченими.
 *
 * Тепер розрахункову оплату дозволяють лише фактичні позитивні стани:
 * «Відправлений» (чинне правило магазину) або «Продаж». Негативні результати
 * завжди повертають false. Невідомий/custom статус теж нічого не вигадує.
 */
export function isShippedOrLaterCrmStatus(order, statuses = []) {
  const current = orderDisplayStatus(order, statuses)
  return current.isCrm && crmStatusAllowsCalculatedCardPayment(current.name)
}

export function StatusBadge({ source = 'crm', name, id = '', compact = false, title = '' }) {
  const label = String(name || (id ? `Статус #${id}` : '—'))
  const isNew = isNewStatusName(label)
  return (
    <span
      className={`order-status-badge ${source === 'crm' ? 'crm' : 'legacy'}${compact ? ' compact' : ''}${isNew ? ' is-new' : ''}`}
      title={title || (source === 'crm' ? `SalesDrive${id ? ` · ID ${id}` : ''}` : 'Локальний legacy-статус')}
    >
      <span className="order-status-source">{source === 'crm' ? 'CRM' : 'Legacy'}</span>
      <strong>{label}</strong>
    </span>
  )
}

export function OrderStatusBadge({ order, crmStatuses = [], compact = false }) {
  const status = orderDisplayStatus(order, crmStatuses)
  const fetched = order?.crm_fetched_at
    ? ` · прочитано ${new Date(order.crm_fetched_at).toLocaleString('uk-UA')}`
    : ''
  return (
    <StatusBadge
      source={status.source}
      name={status.name}
      id={status.id}
      compact={compact}
      title={status.isCrm ? `SalesDrive${status.id ? ` · ID ${status.id}` : ''}${fetched}` : 'Історичне замовлення без SalesDrive'}
    />
  )
}

/** Dropdown статусів CRM. */
export function SalesDriveStatusSelect({ order, statuses = [], disabled = false, onChange }) {
  const current = orderDisplayStatus(order, statuses)
  const currentId = current.isCrm ? current.id : ''
  const hasCurrent = currentId && statuses.some((item) => String(item.id) === currentId)
  const canChange = !disabled && statuses.length > 0

  return (
    <select
      className="order-crm-status-select"
      value={currentId}
      disabled={!canChange}
      onChange={(event) => {
        const option = statuses.find((item) => String(item.id) === event.target.value)
        if (option) onChange?.(option)
      }}
      aria-label={`Статус SalesDrive замовлення №${order?.id ?? ''}`}
      title={statuses.length ? 'Статуси отримані напряму з SalesDrive' : 'Не вдалося завантажити довідник статусів SalesDrive'}
    >
      {!currentId && <option value="">Очікує статус із CRM</option>}
      {currentId && !hasCurrent && <option value={currentId}>{current.name}</option>}
      {statuses.map((item) => <option key={item.id} value={String(item.id)}>{item.name}</option>)}
    </select>
  )
}

/**
 * Довідник статусів SalesDrive з виділенням поточного значення.
 *
 * Не малюємо вигадану «історію» галочками. /api/statuses/ повертає довідник
 * можливих значень, а не журнал переходів конкретної заявки. Отже з позиції
 * «Видалений» не можна робити висновок, що заявка проходила «Продаж».
 */
export function SalesDriveStatusProgress({ order, statuses = [] }) {
  const current = orderDisplayStatus(order, statuses)
  if (!current.isCrm || statuses.length < 2) return null

  const currentIndex = statuses.findIndex((item) => String(item.id) === current.id)
  if (currentIndex < 0) return null
  const outcome = crmBusinessOutcomeName(current.name)

  return (
    <div className="crm-status-progress-wrap">
      <div className="crm-status-progress-head">
        <span>Статуси CRM</span>
        <small>поточний: {current.name}</small>
      </div>
      <div className="crm-status-progress" role="list" aria-label="Статуси SalesDrive; виділено поточний">
        {statuses.map((item, index) => {
          const active = index === currentIndex
          const itemOutcome = crmBusinessOutcomeName(item.name)
          return (
            <div
              key={item.id}
              role="listitem"
              aria-current={active ? 'true' : undefined}
              className={`crm-status-step${active ? ' current' : ''}${active && outcome === 'refusal' ? ' negative' : ''}${itemOutcome === 'refusal' ? ' terminal-negative' : ''}`}
              title={active ? 'Поточний статус заявки' : 'Доступний статус CRM — не означає, що заявка його проходила'}
            >
              <span className="crm-status-step-dot" aria-hidden="true" />
              <span className="crm-status-step-label">{item.name}</span>
            </div>
          )
        })}
      </div>
      <p className="faint crm-status-progress-note">Показано довідник статусів. Галочки проходження не будуються, бо SalesDrive не передає тут історію переходів заявки.</p>
    </div>
  )
}
