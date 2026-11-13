import { useCallback, useEffect, useRef, useState } from 'react'
import { authorizedFetch } from '../api'

const LABELS = { photo: 'Фото', video: 'Відео', voice: 'Голосове', document: 'Документ' }

/** Authenticated, on-demand media for BOTH dashboard chat types.
 * Playback never exposes Telegram bot token; large videos are not fetched
 * until the manager explicitly opens them. Object URLs are reclaimed.
 */
export function ChatAttachment({ fileUrl, message }) {
  const kind = message.file_kind || 'document'
  const isPdf = kind === 'document' && /\.pdf$/i.test(message.file_name || '')
  const [previewPdf, setPreviewPdf] = useState(false)
  const label = LABELS[kind] || 'Файл'
  const [src, setSrc] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [codecError, setCodecError] = useState(false)
  const urlRef = useRef(null)
  const inFlight = useRef(false)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    }
  }, [])

  const load = useCallback(async () => {
    if (inFlight.current || urlRef.current) return
    inFlight.current = true
    setLoading(true)
    setError('')
    try {
      const response = await authorizedFetch(fileUrl, {}, 60000)
      if (!response.ok) {
        const status = response.status
        if (status === 410) throw new Error(`${label} більше недоступний`)
        if (status === 413) throw new Error('Файл завеликий для перегляду через Telegram')
        throw new Error(`Не вдалося завантажити файл (HTTP ${status})`)
      }
      const objectUrl = URL.createObjectURL(await response.blob())
      if (mounted.current) {
        urlRef.current = objectUrl
        setSrc(objectUrl)
      } else URL.revokeObjectURL(objectUrl)
    } catch (err) {
      if (mounted.current) setError(err.message || 'Файл недоступний')
    } finally {
      inFlight.current = false
      if (mounted.current) setLoading(false)
    }
  }, [fileUrl, label])

  useEffect(() => { if (kind === 'photo') load() }, [kind, load])

  if (error) return (
    <div className="chat-file-error" role="alert">
      <span>{error}</span> <button type="button" className="btn ghost small" onClick={load}>Повторити</button>
    </div>
  )
  if (!src) {
    if (kind === 'photo') return <div className="faint support-file-state">Фото завантажується…</div>
    return <button type="button" className="btn ghost small chat-file-action" onClick={load} disabled={loading}>
      {loading ? 'Завантажуємо…' : kind === 'video' ? '▶ Переглянути відео' : kind === 'voice' ? '♫ Слухати голосове' : isPdf ? `📄 Переглянути PDF · ${message.file_name || 'Документ'}` : `↓ ${message.file_name || label}`}
    </button>
  }
  if (kind === 'photo') return (
    <a href={src} target="_blank" rel="noreferrer" aria-label="Переглянути фото">
      <img className="bubble-photo" src={src} alt={message.file_name || 'Фото'} loading="lazy" />
    </a>
  )
  if (kind === 'video') return (
    <div className="chat-video-wrapper">
      <video controls playsInline preload="metadata" src={src} className="bubble-photo chat-video-inline" aria-label={message.file_name || 'Відео'} onError={() => setCodecError(true)} />
      {codecError && <p className="faint" role="status">Цей кодек не підтримується браузером. Спробуйте зберегти відео.</p>}
      <a className="chat-video-save" href={src} download={message.file_name || 'video.mp4'}>Зберегти відео</a>
    </div>
  )
  if (isPdf) return (
    <div className="chat-pdf">
      <div className="chat-pdf-actions">
        <button type="button" className="btn ghost small" onClick={() => setPreviewPdf(v => !v)} aria-expanded={previewPdf}>
          {previewPdf ? 'Сховати PDF' : 'Переглянути PDF'}
        </button>
        <a href={src} download={message.file_name || 'document.pdf'} className="chat-video-save">Завантажити PDF</a>
      </div>
      {previewPdf && <iframe src={src} sandbox="allow-scripts" loading="lazy" title={`PDF: ${message.file_name || 'Документ'}`} className="chat-pdf-frame" referrerPolicy="no-referrer" />}
      <p className="faint chat-pdf-hint">Якщо перегляд не відкривається, завантажте документ.</p>
    </div>
  )
  if (kind === 'voice') return <audio controls preload="metadata" src={src} className="support-media" />
  return <a className="btn ghost small support-file-link" download={message.file_name || 'file'} href={src}>↓ {message.file_name || label}</a>
}
