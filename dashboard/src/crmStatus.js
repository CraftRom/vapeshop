/**
 * Канонічна семантика статусів SalesDrive для панелі.
 * ID налаштовувані, тому рішення приймаємо за фактичною назвою статусу.
 */
export function normalizeCrmStatusName(value) {
  return String(value || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase('uk-UA')
}

export const CRM_SALE_NAMES = new Set(['продаж', 'sale'])
export const CRM_REFUSAL_NAMES = new Set([
  'відмова', 'повернення', 'повернено', 'видалений', 'видалено',
  'refusal', 'return', 'returned', 'deleted',
])

export function crmBusinessOutcomeName(value) {
  const name = normalizeCrmStatusName(value)
  if (CRM_SALE_NAMES.has(name)) return 'sale'
  if (CRM_REFUSAL_NAMES.has(name)) return 'refusal'
  return 'pending'
}

export function isShippedCrmStatusName(value) {
  const name = normalizeCrmStatusName(value)
  return name.startsWith('відправлен') || name === 'shipped' || name === 'sent'
}

/**
 * Чи дозволяє поточний CRM-статус розрахункове правило карткової оплати.
 * Негативні результати ніколи не дозволяють його, незалежно від позиції
 * статусу в довіднику SalesDrive.
 */
export function crmStatusAllowsCalculatedCardPayment(value) {
  const outcome = crmBusinessOutcomeName(value)
  if (outcome === 'refusal') return false
  if (outcome === 'sale') return true
  return isShippedCrmStatusName(value)
}
