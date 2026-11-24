import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
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

/**
 * Contrast of every visible text node against the background actually behind
 * it (the first opaque ancestor), as rendered — not a guess from single CSS
 * declarations. Text over images or gradients is skipped: its background is
 * not one colour. Large text (≥24 px, or ≥18.66 px bold) needs 3:1, the rest
 * 4.5:1 (WCAG 2.2, 1.4.3). Also reports functional text below `minFont` px;
 * elements marked data-decorative (wordmarks) are exempt from both.
 */
export async function auditText(page, label, check, { minFont = 12 } = {}) {
  const { low, tiny } = await page.evaluate((minFont) => {
    const rgba = (value) => { const n = value.match(/[\d.]+/g)?.map(Number) || [0, 0, 0, 0]; return [n[0], n[1], n[2], n.length > 3 ? n[3] : 1] }
    const lum = ([r, g, b]) => [r, g, b].map((v) => v / 255).map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)).reduce((s, c, i) => s + c * [0.2126, 0.7152, 0.0722][i], 0)
    const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05) }
    const blend = (top, bottom) => [0, 1, 2].map((i) => top[i] * top[3] + bottom[i] * (1 - top[3]))
    const describe = (el) => `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''}`
    const backgroundOf = (el) => {
      const layers = []
      for (let node = el; node; node = node.parentElement) {
        const style = getComputedStyle(node)
        if (style.backgroundImage !== 'none') return null
        const bg = rgba(style.backgroundColor)
        if (bg[3] > 0) { layers.push(bg); if (bg[3] >= 0.99) break }
      }
      let colour = [255, 255, 255]
      for (const layer of layers.reverse()) colour = blend(layer, colour)
      return colour
    }
    const low = new Map(), tiny = new Map()
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let text = walker.nextNode(); text; text = walker.nextNode()) {
      if (!text.textContent.trim()) continue
      const el = text.parentElement
      if (!el || el.closest('[data-decorative], [aria-hidden="true"], .sr-only, svg, option, script, style')) continue
      const style = getComputedStyle(el)
      const box = el.getBoundingClientRect()
      if (!box.width || !box.height || style.visibility === 'hidden' || Number(style.opacity) === 0) continue
      if (el.closest('[disabled], [aria-disabled="true"]')) continue // WCAG exempts inactive controls
      const size = parseFloat(style.fontSize), bold = Number(style.fontWeight) >= 700
      if (size < minFont) tiny.set(describe(el), `${size}px «${text.textContent.trim().slice(0, 24)}»`)
      const bg = backgroundOf(el)
      if (!bg) continue
      const fg = rgba(style.color)
      const shown = fg[3] < 1 ? blend(fg, bg) : fg
      const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5
      const value = ratio(shown, bg)
      if (value < need) low.set(describe(el), `${value.toFixed(2)}:1 «${text.textContent.trim().slice(0, 24)}» rgb(${shown.map(Math.round)}) on rgb(${bg.map(Math.round)})`)
    }
    return { low: [...low].map(([k, v]) => `${k} ${v}`), tiny: [...tiny].map(([k, v]) => `${k} ${v}`) }
  }, minFont)
  check(low.length === 0, `${label}: text meets WCAG AA contrast ${low.slice(0, 8).join(' | ')}`)
  check(tiny.length === 0, `${label}: functional text is at least ${minFont}px ${tiny.slice(0, 8).join(' | ')}`)
}

// W-32: axe-core on top of the checks above. Only violations axe rates
// serious or critical fail the suite; each one is reported with the rule and
// the first offending element so the log alone is enough to find it.
const AXE_SOURCE = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8')
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

export async function auditAxe(page, label, check, { disable = [] } = {}) {
  if (!(await page.evaluate(() => Boolean(window.axe)))) await page.addScriptTag({ content: AXE_SOURCE })
  const violations = await page.evaluate(async ({ tags, disable }) => {
    const rules = Object.fromEntries(disable.map((id) => [id, { enabled: false }]))
    const result = await window.axe.run(document, { runOnly: { type: 'tag', values: tags }, rules, resultTypes: ['violations'] })
    return result.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
      .map((v) => `${v.id} (${v.impact}, ${v.nodes.length}): ${v.nodes[0]?.target?.join(' ')} — ${v.nodes[0]?.failureSummary?.split('\n')[1]?.trim() || v.help}`)
  }, { tags: AXE_TAGS, disable })
  check(violations.length === 0, `${label}: axe-core finds no serious or critical WCAG violations ${violations.join(' | ')}`)
}
