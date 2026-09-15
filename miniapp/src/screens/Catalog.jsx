import { useEffect, useMemo, useState } from 'react'

import { api } from '../api'
import { Field } from '../fields'
import { Photo } from '../photo'
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

/** «товар / товари / товарів» — інакше число читається як помилка. */
function plural(count) {
  const tail = count % 100
  if (tail >= 11 && tail <= 14) return 'товарів'
  if (count % 10 === 1) return 'товар'
  if (count % 10 >= 2 && count % 10 <= 4) return 'товари'
  return 'товарів'
}

function stockLabel(stock) {
  if (stock <= 0) return <span className="stock out">Закінчився</span>
  if (stock < 5) return <span className="stock low">Залишилось {stock}</span>
  return <span className="stock">В наявності</span>
}

function hasFreshStatus(product) {
  if (!product || typeof product !== 'object') return false
  if (product.is_new === true || product.new === true) return true
  const raw = product.status ?? product.badge ?? product.label ?? product.tag ?? ''
  const label = String(raw).trim().toLowerCase()
  return ['new', 'fresh', 'новинка', 'новинки'].includes(label)
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
    <div className={`item ${out ? 'is-out' : ''}`}>
      {/* Ліва колонка — усе, що читають: назва, ціна, склад. Дотик по ній
          відкриває товар. Праворуч — фото й дія, щоб великий палець не
          мандрував через увесь екран між «подивитись» і «купити». */}
      <div className="item-main">
        <button className="item-open" onClick={() => onOpen(product)}>
          <p className="item-title">{product.name}</p>
          {/* Ціна одразу під назвою: у списку її шукають першою, а не
              після опису. */}
          <p className="item-price num">
            <span className="item-price-now">
              {Number(product.price).toFixed(0)} {currency}
            </span>
            {discount > 0 && (
              <>
                <span className="old-price num">{oldPrice.toFixed(0)}</span>
                <span className="discount-badge">−{discount}%</span>
              </>
            )}
          </p>
          {product.description && (
            <p className="item-note clamp">{product.description}</p>
          )}
        </button>

        {/* Наявність і «відкласти» ділять один рядок унизу картки.
            Раніше сердечко стояло окремим рядком під описом і робило
            кожну картку на 50 px вищою без жодної нової інформації. */}
        <div className="item-foot">
          <span className="item-meta">{stockLabel(product.stock)}</span>
          {onSave && (
            <button
              className={`heart small ${saved ? 'on' : ''} ${saveLabel ? 'labeled' : ''}`}
              onClick={() => onSave(product)}
              aria-label={saveLabel || (saved ? 'У списку бажаного' : 'Відкласти')}
              title={saveLabel || (saved ? 'У списку бажаного' : 'Відкласти')}
            >
              {/* Сама іконка, без підпису: у рядку списку її розуміють і
                  так. Стан читається і кольором, і заливкою серця, а
                  aria-label для читача екрана лишився повним. */}
              {saveLabel || (saved ? '♥' : '♡')}
            </button>
          )}
        </div>
      </div>

      <div className="item-side">
        <Photo product={product} className="item-photo" />
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
    </div>
  )
}

/* Колись каталог отримував «насіння» з /bootstrap і малював перший екран
 * без окремого запиту. Bootstrap вітрина не викликає вже давно: насіння
 * завжди було null, а гілки під нього — мертвим кодом, який вводив в
 * оману при читанні. Прибрано разом із ніколи не викликаним setSeed. */
export function Catalog({ config, cart, onCartChange, onOpenProduct, wishlists, onSave }) {
  const [categories, setCategories] = useState([])
  const [products, setProducts] = useState(null)
  const [active, setActive] = useState(null)
  const [search, setSearch] = useState('')
  // Порядок і фільтр — на боці вітрини. Сервер віддає категорію цілком,
  // а перекладати сортування на нього означало б новий запит на кожне
  // натискання й порожній екран між ними.
  const [sort, setSort] = useState('default')
  const [inStock, setInStock] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.categories().then(setCategories).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
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

  const view = useMemo(() => {
    if (!products) return null
    // Немає в наявності — не помилка списку, але коли шукають, що купити
    // зараз, ці рядки лише заважають. Тому фільтр є, але вимкнений: за
    // замовчуванням показуємо весь асортимент.
    let rows = inStock ? products.filter((p) => p.stock > 0) : [...products]
    if (sort === 'cheap') rows.sort((a, b) => Number(a.price) - Number(b.price))
    if (sort === 'pricey') rows.sort((a, b) => Number(b.price) - Number(a.price))
    // «Новинки» — за спаданням номера товару. Дати створення в каталозі
    // немає, а номер зростає з кожним доданим товаром, тож порядок той
    // самий. Якщо колись знадобиться справжня дата — це місце для неї.
    if (sort === 'fresh') rows = rows.filter(hasFreshStatus)
    return rows
  }, [products, sort, inStock])

  const hasFreshProducts = useMemo(() => (products || []).some(hasFreshStatus), [products])

  const filtered = sort !== 'default' || inStock || Boolean(search.trim())

  const reset = () => {
    setSearch('')
    setSort('default')
    setInStock(false)
  }

  const qtyOf = (id) => cart?.lines?.find((l) => l.product_id === id)?.qty || 0
  // Один набір на весь список замість пошуку по кожній картці
  const savedIds = new Set((wishlists || []).flatMap((w) => w.product_ids || []))

  return (
    <>
      {/* Заставки «Каталог / Швидкий вибір» тут більше немає: вкладка
          вже називає розділ, а блок відсував перший товар за край екрана.
          Каталог починається з пошуку — з того, чим користуються. */}
      <div className="field search catalog-search">
        {/* Той самий компонент, що й у формі замовлення: цей WebView не
            малює текст у полі сам, і пошук страждав від того ж, від чого
            й оформлення. Дві різні реалізації поля розійшлися б при
            першій же правці. */}
        <Field
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Шукати товар за назвою"
          inputMode="search"
        />
        {search && (
          <button className="search-clear" onClick={() => setSearch('')} aria-label="Очистити">
            ✕
          </button>
        )}
      </div>

      {categories.length > 0 && (
        <div className="rail" role="group" aria-label="Категорії">
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

      <div className="rail rail-sort" role="group" aria-label="Сортування і фільтри">
        <button className="chip" aria-pressed={sort === 'default'}
                onClick={() => setSort('default')}>
          За порядком
        </button>
        <button className="chip" aria-pressed={sort === 'cheap'}
                onClick={() => setSort('cheap')}>
          Дешевші
        </button>
        <button className="chip" aria-pressed={sort === 'pricey'}
                onClick={() => setSort('pricey')}>
          Дорожчі
        </button>
        {hasFreshProducts && (
          <button className="chip" aria-pressed={sort === 'fresh'}
                  onClick={() => setSort('fresh')}>
            Новинки
          </button>
        )}
        <button className="chip" aria-pressed={inStock}
                onClick={() => setInStock((on) => !on)}>
          В наявності
        </button>
      </div>

      {error && <div className="banner warn">{error}</div>}

      {products === null ? (
        <div className="list">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="skeleton" />
          ))}
        </div>
      ) : view.length === 0 ? (
        <div className="empty">
          <h2>Нічого не знайшли</h2>
          <p>
            {inStock && products.length > 0
              ? 'Усе з цього переліку зараз закінчилось.'
              : search
                ? 'Спробуйте іншу назву або оберіть категорію.'
                : 'У цій категорії поки порожньо.'}
          </p>
          {/* Порожній екран без виходу — глухий кут: людина не завжди
              памʼятає, що сама увімкнула фільтр. */}
          {filtered && (
            <div className="actions">
              <button className="secondary" onClick={reset}>Скинути пошук і фільтри</button>
            </div>
          )}
        </div>
      ) : (
        <div className="list">
          <p className="found">
            {view.length === products.length
              ? `${view.length} ${plural(view.length)}`
              : `${view.length} із ${products.length}`}
          </p>
          {view.map((p) => (
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
