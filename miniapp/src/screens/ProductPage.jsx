import { useEffect, useState } from 'react'

import { api } from '../api'
import { getInitData, haptic } from '../telegram'

/** Фото товару.
 *
 * photo_url показуємо напряму. Якщо фото завантажене через бота, тягнемо
 * його з нашого проксі — запит потребує підпису, тож просто підставити
 * адресу в src не можна.
 */
function Photo({ product }) {
  const [blobUrl, setBlobUrl] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (product.photo_url) return undefined
    let revoked = null
    let cancelled = false

    fetch(`/api/shop/products/${product.id}/photo`, {
      headers: { 'X-Telegram-Init-Data': getInitData() },
    })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((blob) => {
        if (cancelled) return
        revoked = URL.createObjectURL(blob)
        setBlobUrl(revoked)
      })
      .catch(() => !cancelled && setFailed(true))

    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [product.id, product.photo_url])

  const src = product.photo_url || blobUrl
  if (failed && !product.photo_url) return null
  if (!src) return <div className="product-photo skeleton" />

  return <img className="product-photo" src={src} alt={product.name} />
}

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
      {/* Рядком, щоб сердечко стало праворуч від кнопки повернення */}
      <div className="head row" style={{ alignItems: 'center', gap: 10 }}>
        <button className="chip" onClick={onBack}>
          ← Каталог
        </button>
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

      <Photo product={product} />

      <div className="screen">
        <h1 style={{ margin: '0 0 6px', fontSize: 20, letterSpacing: '-0.02em' }}>
          {product.name}
        </h1>

        <div className="row" style={{ gap: 10, alignItems: 'baseline' }}>
          <span className="price num" style={{ fontSize: 24, marginTop: 0 }}>
            {price.toFixed(0)} <small>{config.currency}</small>
          </span>
          {/* Стара ціна лише коли вона справді вища: інакше «знижка» з
              нульовою вигодою підриває довіру до всіх решти */}
          {oldPrice > price && (
            <span className="old-price num">
              {oldPrice.toFixed(0)} {config.currency}
            </span>
          )}
        </div>

        <p className={`stock ${stock.tone}`} style={{ marginTop: 8 }}>
          {stock.text}
        </p>

        {product.category_name && (
          <p className="hint" style={{ marginTop: 4 }}>{product.category_name}</p>
        )}

        {product.description ? (
          <p className="product-description">{product.description}</p>
        ) : (
          <p className="hint" style={{ marginTop: 16 }}>
            Опис не додано. Питання про товар можна поставити оператору після
            оформлення замовлення.
          </p>
        )}

        {error && <div className="banner warn" style={{ margin: '12px 0' }}>{error}</div>}
      </div>

      {/* Панель дії тримається внизу: рішення «купити» має бути під пальцем
          незалежно від того, наскільки довгий опис */}
      <div className="product-action">
        {qty > 0 ? (
          <>
            <div className="stepper" style={{ flex: 1, justifyContent: 'center' }}>
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
      </div>
    </div>
  )
}
