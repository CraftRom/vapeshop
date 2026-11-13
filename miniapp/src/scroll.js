/** Wheel support for horizontal rails in Telegram Desktop and browsers. */
export function horizontalWheel(event) {
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.deltaX || !event.deltaY) return
  const rail = event.target?.closest?.('.rail, .settings-tabs')
  if (!rail || rail.scrollWidth <= rail.clientWidth) return
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rail.clientWidth : 1
  const before = rail.scrollLeft
  rail.scrollLeft += event.deltaY * unit
  // At either edge the page keeps scrolling normally.
  if (rail.scrollLeft !== before) event.preventDefault()
}

export function trackViewport() {
  const root = document.documentElement
  const update = () => {
    const app = window.Telegram?.WebApp
    // Dynamic height is only for popovers/keyboard; pinned layouts use the
    // stable Telegram viewport, avoiding jumps as the bottom sheet animates.
    const visible = window.visualViewport?.height || window.innerHeight
    const stable = Number(app?.viewportStableHeight) > 0
      ? app.viewportStableHeight : window.innerHeight
    root.style.setProperty('--viewport-height', `${visible}px`)
    root.style.setProperty('--viewport-stable-height', `${stable}px`)
    const tag = document.activeElement?.tagName
    const editing = tag === 'INPUT' || tag === 'TEXTAREA'
    root.classList?.toggle('miniapp-keyboard-open', Boolean(editing && stable - visible > 140))
  }
  update()
  document.addEventListener('focusin', update)
  document.addEventListener('focusout', update)
  window.addEventListener('resize', update)
  window.visualViewport?.addEventListener('resize', update)
  window.Telegram?.WebApp?.onEvent?.('viewportChanged', update)
  return () => {
    document.removeEventListener('focusin', update)
    document.removeEventListener('focusout', update)
    root.classList?.remove('miniapp-keyboard-open')
    window.removeEventListener('resize', update)
    window.visualViewport?.removeEventListener('resize', update)
    window.Telegram?.WebApp?.offEvent?.('viewportChanged', update)
  }
}
