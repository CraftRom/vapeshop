const formatter = new Intl.NumberFormat('uk-UA', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})

export function money(value) {
  return value == null ? '—' : formatter.format(Number(value))
}
