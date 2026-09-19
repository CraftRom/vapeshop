import { STATUS_LABELS } from './StatusRail'

/**
 * Бізнес-ознака «нового» замовлення без прив'язки до ID статусу SalesDrive.
 *
 * ID статусів у CRM налаштовувані, тому конкретний числовий statusId тут не фіксуємо.
 * Для CRM спершу будуємо той самий display-model, що показує інтерфейс, і
 * вже його назву використовуємо для маркування. Legacy має стабільний
 * технічний код `new`.
 */
export function isNewStatusName(value) {
  const name = String(value || '').trim().toLocaleLowerCase('uk-UA')
  return ['новий', 'нове', 'new'].includes(name)
}

/**
 * Один display-model статусу для всієї панелі.
 *
 * CRM-linked замовлення ніколи не підписуємо через local order.status:
 * statusId/statusName приходять із SalesDrive. Локальний workflow лишається
 * технічним дзеркалом для сповіщень/складу й використовується у UI тільки для
 * історичних замовлень, яких немає в CRM.
 */
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
    source: 'legacy',
    id,
    name: STATUS_LABELS[id] || id || '—',
    isCrm: false,
  }
}

export function isNewOrderStatus(order, crmStatuses = []) {
  if (!order) return false
  const status = orderDisplayStatus(order, crmStatuses)
  return status.isCrm ? isNewStatusName(status.name) : status.id === 'new'
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

/**
 * Dropdown статусів CRM. Поточний statusId не зникає, навіть якщо довідник
 * щойно змінився: показуємо stored value окремою option, але змінювати можна
 * тільки на статуси, які SalesDrive віддає зараз.
 */
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
      {statuses.map((item) => (
        <option key={item.id} value={String(item.id)}>{item.name}</option>
      ))}
    </select>
  )
}

/**
 * Послідовність статусів так, як її повертає SalesDrive.
 *
 * Для робочої картки діє проста модель: якщо поточний статус знаходиться
 * далі у CRM-списку, усі етапи ліворуч уже пройдено. Це лише візуальна
 * історія процесу; фінансові/складські побічні ефекти як і раніше виконує
 * backend через свій workflow, а не браузер.
 */
export function SalesDriveStatusProgress({ order, statuses = [] }) {
  const current = orderDisplayStatus(order, statuses)
  if (!current.isCrm || statuses.length < 2) return null

  const currentIndex = statuses.findIndex((item) => String(item.id) === current.id)
  if (currentIndex < 0) return null

  return (
    <div className="crm-status-progress-wrap">
      <div className="crm-status-progress-head">
        <span>Етапи CRM</span>
        <small>{currentIndex + 1} з {statuses.length}</small>
      </div>
      <div className="crm-status-progress" role="list" aria-label="Послідовність статусів SalesDrive">
        {statuses.map((item, index) => {
          const passed = index < currentIndex
          const active = index === currentIndex
          return (
            <div
              key={item.id}
              role="listitem"
              aria-current={active ? 'step' : undefined}
              className={`crm-status-step${passed ? ' passed' : ''}${active ? ' current' : ''}`}
              title={passed ? 'Етап уже пройдено' : active ? 'Поточний статус' : 'Наступний етап'}
            >
              <span className="crm-status-step-dot" aria-hidden="true">{passed ? '✓' : ''}</span>
              <span className="crm-status-step-label">{item.name}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
