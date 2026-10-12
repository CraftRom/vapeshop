export const PAGE_SIZE = 50
export function pageNumber(value) {
  return Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : 1
}
export function Pagination({ page, total, size = PAGE_SIZE, count, loading, onPage }) {
  const pages = Math.max(1, Math.ceil(total / size))
  return (
    <nav className="list-pagination" aria-label="Сторінки списку">
      <span role="status">Усього: <strong>{total}</strong> · Сторінка {page} з {pages} · Показано: {count || 0}</span>
      <div className="row">
        <button className="btn ghost small" disabled={loading || page <= 1} onClick={() => onPage(page - 1)}>Попередня</button>
        {page > pages && <button className="btn ghost small" disabled={loading} onClick={() => onPage(pages)}>До останньої сторінки</button>}
        <button className="btn ghost small" disabled={loading || page >= pages} onClick={() => onPage(page + 1)}>Наступна</button>
      </div>
    </nav>
  )
}
