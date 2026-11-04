/** Cheap read-side plan: always refresh live orders, defer less urgent data.
 * The detail tab and checkout get immediate reads; active order invalidations
 * arrive separately through SSE. No server state is considered authoritative
 * unless it has been re-read with a signed API call. */
export function backgroundSyncPlan(view, cycle) {
  return {
    active: true,
    history: view === 'profile',
    profile: view === 'profile' || view === 'checkout' || cycle % 3 === 0,
    saved: view === 'profile' || cycle % 3 === 0,
    cart: cycle % 2 === 0,
    config: cycle % 4 === 0,
  }
}

export function realtimeSyncPlan(view) {
  return {
    active: true,
    history: view === 'profile' || view === 'chat',
    profile: view === 'profile' || view === 'checkout',
  }
}
