let depth = 0
let previousOverflow = ''
const dialogs = []

export function mountDialog(element, onClose) {
  if (!element) return () => {}
  const previousFocus = document.activeElement
  dialogs.push(element)
  if (depth++ === 0) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  const focusable = () =>
    [
      ...element.querySelectorAll(
        'button, input, select, textarea, a[href], [tabindex]',
      ),
    ].filter(
      (node) =>
        !node.disabled && node.tabIndex >= 0 && node.getClientRects().length,
    )
  ;(focusable()[0] || element).focus({ preventScroll: true })
  const onKey = (event) => {
    if (dialogs.at(-1) !== element) return
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab') return
    const nodes = focusable()
    if (!nodes.length) {
      event.preventDefault()
      element.focus()
      return
    }
    const first = nodes[0],
      last = nodes[nodes.length - 1]
    if (
      event.shiftKey &&
      (document.activeElement === first ||
        !element.contains(document.activeElement))
    ) {
      event.preventDefault()
      last.focus()
    } else if (
      !event.shiftKey &&
      (document.activeElement === last ||
        !element.contains(document.activeElement))
    ) {
      event.preventDefault()
      first.focus()
    }
  }
  document.addEventListener('keydown', onKey)
  return () => {
    document.removeEventListener('keydown', onKey)
    const index = dialogs.indexOf(element)
    if (index >= 0) dialogs.splice(index, 1)
    if (--depth === 0) document.body.style.overflow = previousOverflow
    if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
  }
}
