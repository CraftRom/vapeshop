export const PROMO_TIMEZONE = 'Europe/Kyiv'
const MAX_MONEY = 9999999999.99
const MAX_USES = 2147483647

export function promoDateInput(value) {
  if (!value) return ''
  // SQLite/older API replies can omit the UTC suffix.
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`)
  if (!Number.isFinite(date.getTime())) return ''
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: PROMO_TIMEZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(date)
  const part = (type) => parts.find((p) => p.type === type).value
  return `${part('year')}-${part('month')}-${part('day')}`
}

export function validatePromoForm(form) {
  const errors = {}
  const code = form.code.trim().toUpperCase()
  if ([...code].length < 2 || [...code].length > 32) errors.code = 'Код має містити від 2 до 32 символів.'
  else if (/[\s\p{C}]/u.test(code)) errors.code = 'Код не може містити пробіли або керівні символи.'

  const money = (value) => /^(?:\d+(?:\.\d{1,2})?|\.\d{1,2})$/.test(String(value)) && Number(value) <= MAX_MONEY
  if (!money(form.value) || Number(form.value) <= 0) errors.value = 'Укажіть додатну знижку, не більше двох знаків після коми.'
  else if (form.type === 'percent' && Number(form.value) > 100) errors.value = 'Відсоткова знижка не може перевищувати 100%.'
  if (!money(form.min_order)) errors.min_order = 'Укажіть суму від 0, не більше двох знаків після коми.'
  for (const key of ['max_uses', 'per_user_limit']) {
    if (key === 'max_uses' && form[key] === '') continue
    if (!/^\d+$/.test(String(form[key])) || Number(form[key]) < 1 || Number(form[key]) > MAX_USES) {
      errors[key] = 'Укажіть ціле число від 1 до 2 147 483 647.'
    }
  }
  if (form.expires_at) {
    const value = form.expires_at
    const parsed = new Date(`${value}T00:00:00Z`)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value < '0001-01-01' || value > '9999-12-30'
      || !Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
      errors.expires_at = 'Укажіть коректну дату завершення.'
    }
  }
  return errors
}

export function promoPayload(form, original) {
  const payload = {
    code: form.code.trim().toUpperCase(), type: form.type,
    value: form.value, min_order: form.min_order,
    max_uses: form.max_uses === '' ? null : Number(form.max_uses),
    per_user_limit: Number(form.per_user_limit), is_active: form.is_active,
    category_ids: form.category_ids ?? [],
  }
  // Preserve an existing timestamp when only another field is edited.
  if (form.expires_at && form.expires_at === promoDateInput(original?.expires_at)) {
    const value = original.expires_at
    payload.expires_at = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`
  } else if (form.expires_at) payload.expires_on = form.expires_at
  else payload.expires_at = null
  return payload
}
