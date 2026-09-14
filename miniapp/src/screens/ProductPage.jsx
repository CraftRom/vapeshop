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
      <div className="head row product-page-head" style={{ alignItems: 'center', gap: 10 }}>
        <button className="chip" onClick={onBack}>
          ← Каталог
        </button>
      </div>

      <div className="product-photo-frame">
        <div className="product-photo-glow" aria-hidden="true" />
        <Photo product={product} />
      </div>

      <div className="screen product-layout">
        <div className="product-summary-card">
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

          <p className="product-lead hint">
            Швидке оформлення в Mini App, актуальна наявність і зручне додавання в кошик.
          </p>
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

        {error && <div className="banner warn" style={{ margin: '0 0 4px' }}>{error}</div>}
      </div>

      <div className="product-action">
        {qty > 0 ? (
          <>
            <div className="stepper product-stepper">
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
            <button className="add" onClick={onBack} style={{ flex: 1 }}>
              Готово
            </button>
          </>
        ) : (
          <button
            className="add"
            style={{ flex: 1, padding: '14px 16px' }}
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
