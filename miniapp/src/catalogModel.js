export const DEFAULT_SORT = 'fresh'

export const SORT_OPTIONS = [
  { value: 'fresh', label: 'Новинки' },
  { value: 'default', label: 'За порядком' },
  { value: 'cheap', label: 'За зростанням ціни' },
  { value: 'pricey', label: 'За спаданням ціни' },
  { value: 'sale', label: 'Акції' },
  { value: 'nameAsc', label: 'За алфавітом, А–Я' },
  { value: 'nameDesc', label: 'За алфавітом, Я–А' },
]

export function hasFreshStatus(product) { return product?.is_new === true }
export function hasSaleStatus(product) { return product?.is_sale === true && Number(product.old_price) > Number(product.price) }
export const catalogPrice = (value) => Number(value).toLocaleString('uk-UA', { maximumFractionDigits: 2 })

const names = new Intl.Collator('uk', { numeric: true, sensitivity: 'base' })

export function discountPercent(product) {
  const old = Number(product.old_price), price = Number(product.price)
  if (!hasSaleStatus(product)) return 0
  if (!Number.isFinite(old) || !Number.isFinite(price) || old <= price || price < 0) return 0
  return Math.floor(((old - price) * 100) / old + 1e-9)
}

// Sorting never mutates the API response. New and sale views use actual product data.
export function sortProducts(products, sort = 'default', inStock = false) {
  let rows = inStock ? products.filter((p) => Number(p.stock) > 0) : [...products]
  if (sort === 'fresh') rows = rows.filter(hasFreshStatus)
  if (sort === 'sale') rows = rows.filter(hasSaleStatus)
  if (sort === 'cheap') rows.sort((a, b) => Number(a.price) - Number(b.price))
  if (sort === 'pricey') rows.sort((a, b) => Number(b.price) - Number(a.price))
  if (sort === 'nameAsc') rows.sort((a, b) => names.compare(a.name || '', b.name || ''))
  if (sort === 'nameDesc') rows.sort((a, b) => names.compare(b.name || '', a.name || ''))
  return rows
}
