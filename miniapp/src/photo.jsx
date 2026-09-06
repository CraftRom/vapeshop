/** Фото товару.
 *
 * Винесене окремо, бо потрібне і в списку, і на сторінці товару. Логіка
 * тут не декоративна: photo_url показуємо напряму, а фото, завантажене
 * через бота, тягнемо з нашого проксі — той запит потребує підпису, тож
 * просто підставити адресу в src не можна.
 */
import { useEffect, useState } from 'react'

import { getInitData } from './telegram'

export function Photo({ product, className = 'product-photo' }) {
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
  // Товар без фото — не поломка: у списку тоді просто немає картинки, і
  // місце під неї не резервується.
  if (failed && !product.photo_url) return null
  if (!src) return <div className={`${className} skeleton`} />

  return <img className={className} src={src} alt={product.name} loading="lazy" />
}
