/** In-flight photo deduplication with ref-counted, bounded object URL cache.
 * Mounted cards can share one image without either card revoking the other's
 * URL. Eviction never revokes a URL that is currently in use. */
export function createPhotoCache(load, revoke, { maxItems = 24, ttlMs = 60000, clock = Date.now } = {}) {
  const cache = new Map()

  function evict(entry) {
    if (entry.refs > 0 || !entry.url) return false
    cache.delete(entry.id)
    revoke(entry.url)
    return true
  }

  function trim() {
    const now = clock()
    for (const entry of [...cache.values()]) {
      if (entry.refs === 0 && entry.url && now - entry.lastUsed >= ttlMs) evict(entry)
    }
    if (cache.size <= maxItems) return
    for (const entry of [...cache.values()]) {
      if (cache.size <= maxItems) break
      evict(entry)
    }
  }

  function acquire(id) {
    trim()
    let entry = cache.get(id)
    if (!entry) {
      entry = { id, refs: 0, url: null, lastUsed: clock(), promise: null }
      entry.promise = Promise.resolve().then(() => load(id))
        .then((url) => {
          entry.url = url
          // Nobody needs an image downloaded after unmount; never retain it.
          if (entry.refs === 0) evict(entry)
          return url
        }, (error) => {
          if (cache.get(id) === entry) cache.delete(id)
          throw error
        })
      cache.set(id, entry)
    }
    entry.refs++
    entry.lastUsed = clock()
    // Recent item goes to the back. Old unused photos are evicted first.
    cache.delete(id)
    cache.set(id, entry)
    let released = false
    return {
      promise: entry.promise,
      release() {
        if (released) return
        released = true
        entry.refs = Math.max(0, entry.refs - 1)
        entry.lastUsed = clock()
        trim()
      },
    }
  }

  return { acquire, size: () => cache.size, trim }
}
