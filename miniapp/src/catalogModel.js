export const DEFAULT_SORT = 'fresh'

export const SORT_OPTIONS = [
  { value: 'fresh', label: 'Спочатку новинки' },
  { value: 'default', label: 'За порядком' },
  { value: 'cheap', label: 'За зростанням ціни' },
  { value: 'pricey', label: 'За спаданням ціни' },
  { value: 'sale', label: 'Спочатку акції' },
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

// Merchandising changes order, never membership. Stable ties retain server order.
export function sortProducts(products, sort = 'default', inStock = false) {
  const rows = inStock ? products.filter((p) => Number(p.stock) > 0) : [...products]
  if (sort === 'fresh') rows.sort((a, b) => Number(hasFreshStatus(b)) - Number(hasFreshStatus(a)))
  if (sort === 'sale') rows.sort((a, b) => Number(hasSaleStatus(b)) - Number(hasSaleStatus(a)))
  if (sort === 'cheap') rows.sort((a, b) => Number(a.price) - Number(b.price))
  if (sort === 'pricey') rows.sort((a, b) => Number(b.price) - Number(a.price))
  if (sort === 'nameAsc') rows.sort((a, b) => names.compare(a.name || '', b.name || ''))
  if (sort === 'nameDesc') rows.sort((a, b) => names.compare(b.name || '', a.name || ''))
  return rows
}

const groupId = (value) => (typeof value === 'number' || typeof value === 'string') && value !== '' && Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : null

export function normalizeCatalogState(state = {}) {
  return {
    active: groupId(state.active), subcategory: groupId(state.subcategory),
    ungrouped: state.ungrouped === true, inStock: state.inStock === true,
    search: typeof state.search === 'string' ? state.search : '',
    sort: SORT_OPTIONS.some((option) => option.value === state.sort) ? state.sort : DEFAULT_SORT,
  }
}

// A deleted/moved group or string ID from restored navigation cannot lock the catalog.
export function resolveCatalogState(state, categories, subcategories) {
  const next = normalizeCatalogState(state)
  if (next.ungrouped) return { ...next, active: null, subcategory: null }
  if (!categories.some((category) => Number(category.id) === next.active)) next.active = null
  const sub = subcategories.find((item) => Number(item.id) === next.subcategory)
  const parent = groupId(sub?.category_id)
  if (!sub || (parent !== null && !categories.some((category) => Number(category.id) === parent))) next.subcategory = null
  else next.active = parent
  return next
}

// Public products remain an array for existing clients; fetch all pages for global ordering.
export async function loadCatalogProducts(fetchPage, params, isCancelled = () => false) {
  const limit = 500, rows = [], seen = new Set()
  for (let offset = 0; !isCancelled(); offset += limit) {
    const page = await fetchPage({ ...params, limit, offset })
    if (isCancelled()) return []
    if (!Array.isArray(page)) throw new Error('Некоректна відповідь каталогу')
    for (const item of page) {
      if (seen.has(item.id)) throw new Error('Каталог змінився під час завантаження. Повторіть спробу.')
      seen.add(item.id); rows.push(item)
    }
    if (page.length < limit) return rows
  }
  return []
}
