/** Shares only *concurrent* GETs. Never caches responses or mutations. */
export function createGetCoordinator() {
  const pending = new Map()
  let scope = null
  return {
    run(path, identity, producer) {
      if (identity !== scope) {
        scope = identity
        pending.clear()
      }
      if (pending.has(path)) return pending.get(path)
      const task = Promise.resolve().then(producer)
      pending.set(path, task)
      void task.then(() => {
        if (pending.get(path) === task) pending.delete(path)
      }, () => {
        if (pending.get(path) === task) pending.delete(path)
      })
      return task
    },
    clear() { scope = null; pending.clear() },
    size() { return pending.size },
  }
}
