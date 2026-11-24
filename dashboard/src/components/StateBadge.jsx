// UI-015: a state is text + tone + a shape cue, never colour alone.
//
// `tone` takes the semantic names; the short legacy names that pages already
// compute (ok / warn / bad) are accepted so callers can migrate gradually.
const TONES = {
  success: { className: 'ok', glyph: '✓' },
  warning: { className: 'warn', glyph: '!' },
  danger: { className: 'bad', glyph: '✕' },
  info: { className: 'info', glyph: 'i' },
  neutral: { className: '', glyph: '' },
}
const ALIASES = { ok: 'success', warn: 'warning', bad: 'danger', '': 'neutral' }

export function stateTone(tone) {
  const name = ALIASES[tone ?? ''] || tone
  return TONES[name] ? name : 'neutral'
}

export function StateBadge({ tone = 'neutral', children, title, className = '' }) {
  const name = stateTone(tone)
  const { className: toneClass, glyph } = TONES[name]
  return (
    <span className={['chip', 'state-badge', toneClass, className].filter(Boolean).join(' ')} data-tone={name} title={title}>
      {glyph && <span className="state-badge-glyph" aria-hidden="true">{glyph}</span>}
      {children}
    </span>
  )
}
