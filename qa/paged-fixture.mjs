// New paged endpoints keep old array responses when paginated is omitted.
export function pageFixture(route, data) {
  const url = new URL(route.request().url())
  if (url.searchParams.get('paginated') !== 'true' || !Array.isArray(data)) return data
  const offset = Number(url.searchParams.get('offset') || 0)
  const limit = Number(url.searchParams.get('limit') || 100)
  const items = data.slice(offset, offset + limit)
  return { items, total: data.length, offset, limit, has_more: offset + items.length < data.length }
}
