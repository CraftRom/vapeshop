import { useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { close, haptic } from '../telegram'

/** Той самий 18+ бар'єр, що й у боті. Каталог до підтвердження недоступний. */
export function AgeGate({ config, onConfirmed }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const age = config?.min_age ?? 18

  const confirm = async () => {
    setBusy(true)
    try {
      const updated = await api.confirmAge()
      onConfirmed(updated)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="gate">
      <div className="gate-mark">{age}+</div>
      <h1>Підтвердження віку</h1>
      <p>
        Товари містять нікотин і продаються лише особам, яким виповнилося {age} років.
      </p>
      <p>
        Нікотин викликає залежність. Продукція не є засобом для відмови від куріння.
      </p>
      {error && <div className="banner warn">{error}</div>}
      <div className="actions">
        <button className="primary" onClick={confirm} disabled={busy}>
          {busy ? 'Хвилинку…' : `Мені є ${age}`}
        </button>
        <button className="secondary" onClick={close}>
          Мені менше — вийти
        </button>
      </div>
    </div>
  )
}

function stockLabel(stock) {
  if (stock <= 0) return <span className="stock out">Немає</span>
  if (stock < 5) return <span className="stock low">Залишилось {stock}</span>
  return <span className="stock">В наявності</span>
}

function ProductCard({ product, qty, currency, onChange }) {
  const out = product.stock <= 0
  const atMax = qty >= product.stock

  return (
    <div className="card">
      <div className="card-body">
        <p className="card-title">{product.name}</p>
        {product.description && <p className="card-note">{product.description}</p>}
        <div className="price num">
          {Number(product.price).toFixed(0)} <small>{currency}</small>
          {'  '}
          {stockLabel(product.stock)}
        </div>
      </div>

      {qty > 0 ? (
        <div className="stepper">
          <button onClick={() => onChange(product, -1)} aria-label="Прибрати одну штуку">
            −
          </button>
          <span className="qty num">{qty}</span>
          <button
            onClick={() => onChange(product, 1)}
            disabled={atMax}
            aria-label="Додати ще одну штуку"
          >
            +
          </button>
        </div>
      ) : (
        <button className="add" disabled={out} onClick={() => onChange(product, 1)}>
          {out ? 'Немає' : 'У кошик'}
        </button>
      )}
    </div>
  )
}

export function Catalog({ config, cart, onCartChange, seed }) {
  const [categories, setCategories] = useState(seed?.categories || [])
  const [products, setProducts] = useState(seed?.products || null)
  const [active, setActive] = useState(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    // Категорії вже прийшли з bootstrap — повторний запит зайвий
    if (seed?.categories?.length) return
    api.categories().then(setCategories).catch((e) => setError(e.message))
  }, [seed])

  const firstRun = useRef(Boolean(seed?.products?.length))

  useEffect(() => {
    // Перший показ бере товари з bootstrap; далі — звичайне довантаження
    if (firstRun.current) {
      firstRun.current = false
      return
    }
    let cancelled = false
    setProducts(null)
    const timer = setTimeout(() => {
      api
        .products({ categoryId: active, search: search.trim() || undefined })
        .then((rows) => !cancelled && setProducts(rows))
        .catch((e) => !cancelled && setError(e.message))
    }, search ? 300 : 0) // пошук чекає паузи в наборі, перемикання категорій — ні
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [active, search])

  const change = async (product, delta) => {
    haptic('light')
    try {
      await onCartChange(product.id, delta)
    } catch (err) {
      setError(err.message)
    }
  }

  const qtyOf = (id) => cart?.lines?.find((l) => l.product_id === id)?.qty || 0

  return (
    <>
      <div className="field" style={{ paddingTop: 12 }}>
        <input
          className="input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Пошук за назвою"
          inputMode="search"
        />
      </div>

      {categories.length > 0 && (
        <div className="rail">
          <button
            className="chip"
            aria-pressed={active === null}
            onClick={() => setActive(null)}
          >
            Усе
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              className="chip"
              aria-pressed={active === c.id}
              onClick={() => setActive(c.id)}
            >
              {c.name}
            </button>
          ))}
        </div>
      )}

      {error && <div className="banner warn">{error}</div>}

      {products === null ? (
        <div className="list">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="skeleton" />
          ))}
        </div>
      ) : products.length === 0 ? (
        <div className="empty">
          <h2>Нічого не знайшли</h2>
          <p>
            {search
              ? 'Спробуйте іншу назву або оберіть категорію.'
              : 'У цій категорії поки порожньо.'}
          </p>
        </div>
      ) : (
        <div className="list">
          {products.map((p) => (
            <ProductCard
              key={p.id}
              product={p}
              qty={qtyOf(p.id)}
              currency={config.currency}
              onChange={change}
            />
          ))}
        </div>
      )}
    </>
  )
}
