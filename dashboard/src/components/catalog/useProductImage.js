import { useEffect, useState } from 'react'
import { api } from '../../api'

export function useProductImage(product) {
  const [image, setImage] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true, objectUrl = ''
    setImage(''); setError('')
    if (!product.photo_url && product.has_photo) {
      api.products.photo(product.id).then((url) => {
        objectUrl = url
        if (alive) setImage(url)
        else URL.revokeObjectURL(url)
      }).catch((err) => alive && setError(err.message))
    }
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [product.id, product.photo_url, product.has_photo])
  return [product.photo_url || image, error]
}
