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

/** Картка товару. Одна на каталог і на сторінку списку бажаного.
 *
 * Друга копія цієї розмітки в «Збереженому» вже відставала: там не було
 * ні лічильника кількості, ні старої ціни, ні значка знижки — той самий
 * товар виглядав по-різному залежно від того, звідки на нього дивишся.
 *
 * saveLabel дозволяє замінити підпис нижньої кнопки: у каталозі це
 * «Відкласти», у списку — «Прибрати».
 */
export function ProductCard({
  product, qty, currency, onChange, onOpen, saved, onSave, saveLabel,
}) {
  const out = product.stock <= 0
  const atMax = qty >= product.stock
  const oldPrice = Number(product.old_price || 0)
  // Відсоток рахуємо тут, а не в розмітці: округлення вниз навмисне —
  // обіцяти «−34%» там, де насправді 33.7%, не варто.
  const discount = oldPrice > Number(product.price)
    ? Math.floor((1 - Number(product.price) / oldPrice) * 100)
    : 0

  return (
    <div className="card">
      {/* Тіло картки — кнопка: дотик по назві чи опису відкриває товар,
          а лічильник праворуч лишається окремою дією */}
      <button className="card-body card-open" onClick={() => onOpen(product)}>
        <p className="card-title">{product.name}</p>
        {product.description && <p className="card-note clamp">{product.description}</p>}
        <div className={`price num ${discount ? 'has-discount' : ''}`}>
          {Number(product.price).toFixed(0)} <small>{currency}</small>
          {discount > 0 && (
            <>
              <span className="old-price num">{oldPrice.toFixed(0)}</span>
              <span className="discount-badge">−{discount}%</span>
            </>
          )}
          {'  '}
          {stockLabel(product.stock)}
        </div>
      </button>

      {/* Права колонка: спершу дія з кошиком, під нею — відкласти.
          Так обидві кнопки під великим пальцем і не конкурують за увагу */}
      <div className="card-actions">
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

      {onSave && (
        <button
          className={`heart small ${saved ? 'on' : ''}`}
          onClick={() => onSave(product)}
          aria-label={saveLabel || (saved ? 'У списку бажаного' : 'Відкласти')}
          title={saveLabel || (saved ? 'У списку бажаного' : 'Відкласти')}
        >
          {/* Стан підписом, а не самим кольором: на дрібній кнопці
              заливка читається погано, а тут одразу видно, що товар уже
              відкладений — і людина не додає його вдруге */}
          {saveLabel || (saved ? '♥ У списку' : '♡ Відкласти')}
        </button>
      )}
      </div>
    </div>
  )
}

export function Catalog({ config, cart, onCartChange, seed, onOpenProduct, wishlists, onSave }) {
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
  // Один набір на весь список замість пошуку по кожній картці
  const savedIds = new Set((wishlists || []).flatMap((w) => w.product_ids || []))

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
              onOpen={onOpenProduct}
              saved={savedIds.has(p.id)}
              onSave={onSave}
            />
          ))}
        </div>
      )}
    </>
  )
}
