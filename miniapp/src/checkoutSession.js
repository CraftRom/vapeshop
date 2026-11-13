/** Fingerprint only fields that determine the order contents/price.
 * Never include PII; this key exists only in RAM, not localStorage.
 */
export function cartSignature(cart) {
  return JSON.stringify((cart?.lines || [])
    .map(({ product_id, qty, price }) => [product_id, qty, price])
    .sort((a, b) => Number(a[0]) - Number(b[0])))
}

/** A draft (including its idempotency key) is safe to resume only when
 * the authoritative server cart still matches its original snapshot.
 */
export function resumeCheckoutDraft(draft, signature) {
  return draft?.signature === signature ? draft : null
}
