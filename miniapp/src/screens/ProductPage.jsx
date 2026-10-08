import { useRef, useState } from 'react'
import { api } from '../api'
import { Photo } from '../photo'
import { StoreIcon } from '../StoreIcon'
import { ProductCard } from './Catalog'
import { haptic } from '../telegram'
import { catalogPrice, hasSaleStatus } from '../catalogModel'

function stockNote(stock) {
  if (stock <= 0) return { text: 'Немає в наявності', tone: 'out' }
  if (stock < 5) return { text: `Залишилось ${stock} шт`, tone: 'low' }
  return { text: 'В наявності', tone: '' }
}

export function ProductPage({ config, product, cart, onCartChange, onBack, onCart, saved, onSave, recentProducts = [], onOpenProduct, backLabel = 'Назад до каталогу' }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [shareStatus, setShareStatus] = useState('')
  const [opening, setOpening] = useState(false)
  const changing = useRef(false)
  const hero = useRef(null)
  const qty = cart?.lines?.find((l) => l.product_id === product.id)?.qty || 0
  const stock = stockNote(product.stock)
  const out = product.stock <= 0
  const oldPrice = Number(product.old_price || 0)
  const discounted = hasSaleStatus(product)
  const price = Number(product.price)
  const longDescription = (product.description || '').length > 280
  const viewed = recentProducts.filter((p) => p.id !== product.id).slice(0, 6)

  const change = async (delta, id = product.id) => {
    if (changing.current) return
    changing.current = true
    setBusy(true)
    setError('')
    haptic('light')
    try { await onCartChange(id, delta) } catch (err) { setError(err.message) }
    finally { changing.current = false; setBusy(false) }
  }
  const share = async () => {
    const text = `${product.name}\n${catalogPrice(price)} ${config.currency}`
    try {
      if (navigator.share) await navigator.share({ title: product.name, text })
      else { await navigator.clipboard.writeText(text); setShareStatus('Назву та ціну скопійовано') }
    } catch (err) { if (err.name !== 'AbortError') setShareStatus('Не вдалося поділитися. Спробуйте ще раз.') }
  }
  // A viewed product may have been removed or repriced: refresh before opening it.
  const openViewed = async (item) => {
    if (opening) return
    setOpening(true)
    setError('')
    try {
      const current = await api.product(item.id)
      if (!current) throw new Error('Цей товар більше недоступний у каталозі.')
      onOpenProduct(current)
    } catch (err) { setError(err.message) }
    finally { setOpening(false) }
  }

  return (
    <article className="store-detail">
      <div className="detail-toolbar">
        <button className="store-icon-button detail-back" onClick={onBack} aria-label={backLabel}><StoreIcon name="back" /><span>Назад</span></button>
        <div className="detail-toolbar-actions">
          {onSave && <button className={`store-icon-button ${saved ? 'is-saved' : ''}`} onClick={onSave} aria-label={saved ? 'У списку бажаного' : 'Зберегти в список'}><StoreIcon name="heart" filled={saved} /></button>}
          {(navigator.share || navigator.clipboard?.writeText) && <button className="store-icon-button" onClick={share} aria-label="Поділитися товаром"><StoreIcon name="share" /></button>}
        </div>
      </div>
      {shareStatus && <p className="detail-share-status hint" role="status">{shareStatus}</p>}
      <div className="detail-layout">
        <div className="detail-gallery">
          <div className="detail-hero" ref={hero}>
            <span className="photo-placeholder"><StoreIcon name="box" /></span>
            <Photo product={product} className="detail-image" loading="eager" />
          </div>
          {(product.has_photo || product.photo_url) && <button className="detail-thumbnail" onClick={() => hero.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })} aria-label="Переглянути фото товару"><Photo product={product} className="detail-thumbnail-image" /></button>}
        </div>
        <div className="detail-info">
          <div className="product-meta">
            {product.category_name && <span className="product-pill">{product.category_name}</span>}
            {product.subcategory_name && <span className="product-pill">{product.subcategory_name}</span>}
            {product.is_new && <span className="product-pill">Новинка</span>}
            {discounted && <span className="product-pill">Акція</span>}
            <span className={`product-pill stock-pill ${stock.tone}`}>{stock.text}</span>
          </div>
          <h1 className="detail-title">{product.name}</h1>
          {product.sku && <p className="detail-sku hint">Артикул (SKU): <span>{product.sku}</span></p>}
          <div className="detail-buy-row">
            <div className="detail-price num">
              {discounted && <span className="old-price">{catalogPrice(oldPrice)} {config.currency}</span>}
              <strong>{catalogPrice(price)} {config.currency}</strong>
              <span className="hint">ціна за шт.</span>
            </div>
            <div className="detail-buy-actions">
              {qty > 0 ? <>
                <div className="stepper">
                  <button onClick={() => change(-1)} disabled={busy} aria-label="Менше">−</button>
                  <span className="qty num" aria-live="polite">{qty}</span>
                  <button onClick={() => change(1)} disabled={busy || out || qty >= product.stock} aria-label="Більше">+</button>
                </div>
                <button className="primary" onClick={onCart}>До кошика</button>
              </> : <button className="primary" disabled={out || busy} onClick={() => change(1)}>{out ? 'Немає в наявності' : 'Додати в кошик'}</button>}
            </div>
          </div>
          {error && <div className="banner warn" role="alert">{error}</div>}
          <section className="detail-copy">
            <h2>Опис товару</h2>
            {product.description ? <p id="product-description" className={`detail-description ${longDescription && !expanded ? 'is-collapsed' : ''}`}>{product.description}</p> : <p className="hint">Опис поки не додано.</p>}
            {longDescription && <button className="secondary detail-expand" aria-expanded={expanded} aria-controls="product-description" onClick={() => setExpanded((value) => !value)}>{expanded ? 'Згорнути' : 'Детальніше'}</button>}
          </section>
        </div>
      </div>
      {viewed.length > 0 && <section className="detail-viewed" aria-busy={opening}>
        <h2>Переглянуті товари</h2>
        <div className="rail viewed-rail" tabIndex={0} aria-label="Переглянуті товари">
          {viewed.map((item) => <ProductCard key={item.id} product={item} qty={cart?.lines?.find((l) => l.product_id === item.id)?.qty || 0} currency={config.currency} onChange={(p, delta) => change(delta, p.id)} onOpen={openViewed} />)}
        </div>
      </section>}
    </article>
  )
}
