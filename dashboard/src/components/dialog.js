let depth = 0
let previousOverflow = ''

export function mountDialog(element, onClose) {
  if (!element) return () => {}
  const previousFocus = document.activeElement
  if (depth++ === 0) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  const focusable = () => [...element.querySelectorAll('button, input, select, textarea, a[href], [tabindex]')]
    .filter((node) => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length)
  ;(focusable()[0] || element).focus({ preventScroll: true })
  const onKey = (event) => {
    if (event.key === 'Escape') { event.preventDefault(); onClose(); return }
    if (event.key !== 'Tab') return
    const nodes = focusable()
    if (!nodes.length) { event.preventDefault(); element.focus(); return }
    const first = nodes[0], last = nodes[nodes.length - 1]
    if (event.shiftKey && (document.activeElement === first || !element.contains(document.activeElement))) {
      event.preventDefault(); last.focus()
    } else if (!event.shiftKey && (document.activeElement === last || !element.contains(document.activeElement))) {
      event.preventDefault(); first.focus()
    }
  }
  element.addEventListener('keydown', onKey)
  return () => {
    element.removeEventListener('keydown', onKey)
    if (--depth === 0) document.body.style.overflow = previousOverflow
    if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
  }
}
