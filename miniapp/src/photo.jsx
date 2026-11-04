/** Фото товару.
 *
 * Винесене окремо, бо потрібне і в списку, і на сторінці товару. Логіка
 * тут не декоративна: photo_url показуємо напряму, а фото, завантажене
 * через бота, тягнемо з нашого проксі — той запит потребує підпису, тож
 * просто підставити адресу в src не можна.
 */
import { useEffect, useState } from 'react'

import { api } from './api'
import { clientLog } from './logger'
import { createPhotoCache } from './photoCache'

const photoCache = createPhotoCache(id => api.productPhoto(id), url => URL.revokeObjectURL(url))

export function Photo({ product, className = 'product-photo', loading = 'lazy' }) {
  const [blobUrl, setBlobUrl] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setBlobUrl(null)
    setFailed(false)
    // has_photo приходить із ProductOut. Без цієї перевірки кожен товар без
    // картинки робив зайвий GET /photo → 404, що засмічувало мережу й журнал.
    if (product.photo_url || !product.has_photo) return undefined
    let cancelled = false
    const image = photoCache.acquire(product.id)
    image.promise
      .then((url) => {
        if (!cancelled) setBlobUrl(url)
      })
      .catch((err) => {
        if (cancelled) return
        setFailed(true)
        clientLog('storefront.photo.failed', {
          level: 'warning',
          message: 'Не вдалося завантажити фото товару',
          productId: product.id,
          status: Number.isFinite(Number(err?.status)) ? Number(err.status) : null,
          errorName: err?.name || '',
          once: `photo-${product.id}`,
        })
      })

    return () => {
      cancelled = true
      image.release()
    }
  }, [product.id, product.photo_url, product.has_photo])

  if (!product.has_photo && !product.photo_url) return null
  const src = product.photo_url || blobUrl
  if (failed) return null
  if (!src) return <div className={`${className} skeleton`} />

  return (
    <img
      className={className}
      src={src}
      alt={product.name}
      loading={loading}
      referrerPolicy="no-referrer"
      decoding="async"
      onError={() => {
        setFailed(true)
        clientLog('storefront.photo.render_failed', {
          level: 'warning', message: 'Браузер не зміг показати фото товару',
          productId: product.id, once: `photo-render-${product.id}`,
        })
      }}
    />
  )
}
