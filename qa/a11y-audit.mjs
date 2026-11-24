// Mechanical accessibility and layout checks shared by the dashboard and the
// Mini App matrices (UI-014 / UI-026). Each check is something that is never
// acceptable, so a failure is a real defect, not a style opinion.
const INTERACTIVE = new Set(['button', 'link', 'textbox', 'searchbox', 'combobox', 'checkbox', 'switch', 'radio', 'spinbutton', 'slider', 'tab', 'menuitem'])

/**
 * Runs every check on the current state of `page` and reports through
 * `check(ok, label)`. `cdp` is a CDP session of the same page; accessible
 * names come from Chromium's own accessibility tree.
 */
export async function auditPage(page, cdp, label, check, { errors = [] } = {}) {
  const h1 = await page.locator('h1:visible').count()
  check(h1 === 1, `${label}: exactly one visible h1 (found ${h1})`)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  check(overflow <= 0, `${label}: no page-wide horizontal scroll (${overflow}px)`)

  const { nodes } = await cdp.send('Accessibility.getFullAXTree')
  const unnamed = nodes.filter((node) => !node.ignored && INTERACTIVE.has(node.role?.value) && !String(node.name?.value || '').trim())
  const described = []
  for (const node of unnamed.slice(0, 8)) {
    if (!node.backendDOMNodeId) { described.push(node.role.value); continue }
    const { object } = await cdp.send('DOM.resolveNode', { backendNodeId: node.backendDOMNodeId })
    const { result } = await cdp.send('Runtime.callFunctionOn', { objectId: object.objectId, returnByValue: true, functionDeclaration: 'function(){const r=this.getBoundingClientRect();return r.width&&r.height?this.outerHTML.slice(0,160):""}' })
    if (result.value) described.push(`${node.role.value} ${result.value}`)
  }
  check(described.length === 0, `${label}: every visible control has an accessible name ${described.join(' | ')}`)

  const duplicates = await page.evaluate(() => { const seen = {}; for (const el of document.querySelectorAll('[id]')) seen[el.id] = (seen[el.id] || 0) + 1; return Object.keys(seen).filter((id) => seen[id] > 1) })
  check(duplicates.length === 0, `${label}: ids are unique ${duplicates.join(', ')}`)

  const small = await page.evaluate(() => [...document.querySelectorAll('button, select, input:not([type=checkbox]):not([type=radio]):not([type=hidden]), [role=button]')]
    .filter((el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && (r.width < 24 || r.height < 24) && !el.closest('.sr-only') })
    .map((el) => `${el.tagName.toLowerCase()}.${String(el.className || '').slice(0, 40)} ${Math.round(el.getBoundingClientRect().width)}×${Math.round(el.getBoundingClientRect().height)} «${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 30)}»`))
  check(small.length === 0, `${label}: controls are at least 24×24 px ${small.slice(0, 6).join(' | ')}`)
  check(errors.length === 0, `${label}: no runtime errors ${errors.join('; ')}`)
}
