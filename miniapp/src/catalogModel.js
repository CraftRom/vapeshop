export const SORT_OPTIONS = [
  { value: 'default', label: 'За порядком' },
  { value: 'fresh', label: 'Новинки' },
  { value: 'cheap', label: 'За зростанням ціни' },
  { value: 'pricey', label: 'За спаданням ціни' },
  { value: 'sale', label: 'Акції' },
  { value: 'nameAsc', label: 'За алфавітом, А–Я' },
  { value: 'nameDesc', label: 'За алфавітом, Я–А' },
]

export function hasFreshStatus(product) {
  if (!product || typeof product !== 'object') return false
  if (product.is_new === true || product.new === true) return true
  const raw = product.status ?? product.badge ?? product.label ?? product.tag ?? ''
  return ['new', 'fresh', 'новинка', 'новинки'].includes(String(raw).trim().toLowerCase())
}

const names = new Intl.Collator('uk', { numeric: true, sensitivity: 'base' })

export function discountPercent(product) {
  const old = Number(product.old_price), price = Number(product.price)
  if (!Number.isFinite(old) || !Number.isFinite(price) || old <= price || price < 0) return 0
  return Math.floor(((old - price) * 100) / old + 1e-9)
}

// Sorting never mutates the API response. New and sale views use actual product data.
export function sortProducts(products, sort = 'default', inStock = false) {
  let rows = inStock ? products.filter((p) => Number(p.stock) > 0) : [...products]
  if (sort === 'fresh') rows = rows.filter(hasFreshStatus)
  if (sort === 'sale') rows = rows.filter((p) => Number(p.old_price) > Number(p.price))
  if (sort === 'cheap') rows.sort((a, b) => Number(a.price) - Number(b.price))
  if (sort === 'pricey') rows.sort((a, b) => Number(b.price) - Number(a.price))
  if (sort === 'nameAsc') rows.sort((a, b) => names.compare(a.name || '', b.name || ''))
  if (sort === 'nameDesc') rows.sort((a, b) => names.compare(b.name || '', a.name || ''))
  return rows
}
