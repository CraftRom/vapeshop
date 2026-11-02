import { createElement } from 'react'

export function plainBroadcastText(text, format = 'plain') {
  if (format !== 'html') return text || ''
  return (
    new DOMParser().parseFromString(text || '', 'text/html').body.textContent ||
    ''
  )
}
export const broadcastLength = (text, format) =>
  [...plainBroadcastText(text, format)].length
export function broadcastValidation(form) {
  const errors = {}
  if (!form.title.trim() || [...form.title.trim()].length > 255)
    errors.title = 'Укажіть назву до 255 знаків.'
  const length = broadcastLength(form.text, form.text_format)
  const limit = form.photo_url ? 1024 : 4096
  if (!plainBroadcastText(form.text, form.text_format).trim())
    errors.text = 'Додайте текст повідомлення.'
  else if (length > limit)
    errors.text = `Ліміт ${limit} знаків. Скоротіть текст або приберіть зображення.`
  if (
    form.photo_url &&
    !(
      /^\/media\/[A-Za-z0-9_-]+\.(jpg|jpeg|png|gif|webp)$/i.test(
        form.photo_url,
      ) || /^https?:\/\/[^\s]+$/i.test(form.photo_url)
    )
  )
    errors.photo_url =
      'Укажіть пряме посилання http(s) або завантажте зображення.'
  if (!!form.button_text.trim() !== !!form.button_url.trim())
    errors.button = 'Для кнопки заповніть текст і посилання.'
  else if (
    form.button_url &&
    !/^(https?:\/\/|tg:\/\/)[^\s]+$/i.test(form.button_url.trim())
  )
    errors.button =
      'Посилання кнопки має починатися з https://, http:// або tg://.'
  return errors
}

export function BroadcastPreviewText({ text, format }) {
  if (format !== 'html') return text
  const doc = new DOMParser().parseFromString(text, 'text/html')
  const allowed = new Set([
    'b',
    'strong',
    'i',
    'em',
    'u',
    'ins',
    's',
    'strike',
    'del',
    'a',
    'code',
    'pre',
    'blockquote',
    'span',
  ])
  const render = (node, key) => {
    if (node.nodeType === 3) return node.textContent
    const tag = node.nodeName.toLowerCase()
    if (!allowed.has(tag)) return node.textContent
    const props = { key }
    if (tag === 'a') {
      const href = node.getAttribute('href') || ''
      if (/^(https?:\/\/|tg:\/\/|mailto:)/i.test(href)) {
        props.href = href
        props.target = '_blank'
        props.rel = 'noopener noreferrer'
      }
    }
    return createElement(
      tag,
      props,
      [...node.childNodes].map((child, i) => render(child, `${key}-${i}`)),
    )
  }
  return [...doc.body.childNodes].map((node, index) =>
    render(node, String(index)),
  )
}
