import { useState } from 'react'

import { Photo } from '../photo'
import { haptic } from '../telegram'

function stockNote(stock) {
  if (stock <= 0) return { text: 'Немає в наявності', tone: 'out' }
  if (stock < 5) return { text: `Залишилось ${stock} шт`, tone: 'low' }
  return { text: 'В наявності', tone: '' }
}

export function ProductPage({ config, product, cart, onCartChange, onBack, saved, onSave }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const qty = cart?.lines?.find((l) => l.product_id === product.id)?.qty || 0
  const stock = stockNote(product.stock)
  const out = product.stock <= 0
  const oldPrice = Number(product.old_price || 0)
  const discount = oldPrice > Number(product.price)
    ? Math.floor((1 - Number(product.price) / oldPrice) * 100)
    : 0
  const price = Number(product.price)

  const change = async (delta) => {
    setBusy(true)
    setError('')
    haptic('light')
    try {
      await onCartChange(product.id, delta)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="product-page">
      <div className="page-back">
        <button className="back" onClick={onBack}>
          Каталог
        </button>
      </div>

      <div className="product-photo-frame">
        <Photo product={product} />
      </div>

      <div className="product-layout">
        <div>
          <div className="product-meta">
            {product.category_name && (
              <span className="product-pill">{product.category_name}</span>
            )}
            <span className={`product-pill stock-pill ${stock.tone}`}>
              {stock.text}
            </span>
          </div>

          <h1 className="product-title">{product.name}</h1>

          <div className="product-price-row">
            <span className="price num product-price-main">
              {price.toFixed(0)} <small>{config.currency}</small>
            </span>
            {discount > 0 && (
              <div className="product-discount-group">
                <span className="old-price num">
                  {oldPrice.toFixed(0)} {config.currency}
                </span>
                <span className="discount-badge">−{discount}%</span>
              </div>
            )}
          </div>
        </div>

        <section className="product-copy-card">
          <h2>Опис</h2>
          {product.description ? (
            <p className="product-description">{product.description}</p>
          ) : (
            <p className="hint">
              Опис поки не додано. Якщо потрібні деталі щодо смаку, характеристик або
              доставки — поставте питання менеджеру після оформлення замовлення.
            </p>
          )}
        </section>

        {error && <div className="banner warn">{error}</div>}
      </div>

      {/* Дія притиснута донизу: рішення «додати» приймають після опису,
          і кнопка має бути під великим пальцем. Головна кнопка тут
          залита — на сторінці товару вона одна й конкурувати їй ні з чим. */}
      <div className="product-action">
        {qty > 0 ? (
          <>
            <div className="stepper">
              <button onClick={() => change(-1)} disabled={busy} aria-label="Менше">
                −
              </button>
              <span className="qty num">{qty}</span>
              <button
                onClick={() => change(1)}
                disabled={busy || qty >= product.stock}
                aria-label="Більше"
              >
                +
              </button>
            </div>
            <button className="primary" onClick={onBack}>
              Готово
            </button>
          </>
        ) : (
          <button
            className="primary"
            disabled={out || busy}
            onClick={() => change(1)}
          >
            {out ? 'Немає в наявності' : 'Додати в кошик'}
          </button>
        )}

        {onSave && (
          <button
            className={`heart ${saved ? 'on' : ''}`}
            onClick={onSave}
            aria-label={saved ? 'У списку бажаного' : 'Зберегти в список'}
            title={saved ? 'У списку бажаного' : 'Зберегти в список'}
          >
            {saved ? '♥' : '♡'}
          </button>
        )}
      </div>
    </div>
  )
}
