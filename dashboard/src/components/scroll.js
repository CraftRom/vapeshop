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

