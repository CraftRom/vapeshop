// Availability is presented beside the same line that must be corrected.
export function cartLineProblem(line) {
  const stock = Number(line.stock)
  if (line.is_available === false || (Number.isFinite(stock) && stock <= 0)) {
    return Number.isFinite(stock) && stock <= 0 ? 'Немає в наявності' : 'Товар недоступний'
  }
  if (Number.isFinite(stock) && stock < Number(line.qty)) return `Доступно лише ${stock} шт. Зменште кількість.`
  return ''
}
export function hasCartProblems(cart) {
  return Boolean(cart?.problems?.length || cart?.lines?.some(line => cartLineProblem(line)))
}
