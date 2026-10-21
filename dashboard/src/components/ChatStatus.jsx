export function ChatStatus({ loading, error, onRetry }) {
  return <div className="chat-sync-status" role="status">
    {error ? <><span title={error}>Не вдалося оновити переписку.</span><button className="btn ghost small" onClick={onRetry}>Повторити</button></>
      : <span className="faint">{loading ? 'Завантажуємо повідомлення…' : 'Повідомлення оновлюються у фоні'}</span>}
  </div>
}

export function ChatLatest({ viewport }) {
  return <div className="chat-latest-slot">
    {viewport.away && <button className="btn small" onClick={viewport.jumpToLatest}>
      {viewport.unseen ? `Нові повідомлення: ${viewport.unseen} ↓` : 'До останніх повідомлень ↓'}
    </button>}
  </div>
}

export function ChatDraftStatus({ text, status }) {
  return <span className="chat-draft-status faint" role="status">
    {text && (status === 'device' ? 'Чернетка збережена на цьому пристрої' : 'Чернетка лише у цій вкладці')}
  </span>
}
