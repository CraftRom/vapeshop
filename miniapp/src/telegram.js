/** Обгортка над Telegram WebApp SDK.
 *
 * Уся робота з window.Telegram зібрана тут, щоб застосунок не падав,
 * якщо його відкрити у звичайному браузері — там SDK просто немає,
 * і кожна функція тихо стає порожньою.
 */
const tg = window.Telegram?.WebApp

const CACHE_KEY = 'tgInitData'
// Android вивантажує процес і відновлює WebView, перезавантажуючи вже
// обрізану адресу. sessionStorage при цьому теж чиститься, тому підпис
// кешуємо надовше. Строк тримаємо коротким: бекенд усе одно відхилить
// initData, старший за добу.
const CACHE_TTL_MS = 12 * 60 * 60 * 1000

function cacheWrite(value) {
  const payload = JSON.stringify({ value, at: Date.now() })
  for (const store of [window.localStorage, window.sessionStorage]) {
    try {
      store.setItem(CACHE_KEY, payload)
    } catch {
      /* приватний режим або переповнення — просто пропускаємо */
    }
  }
}

function cacheRead() {
  for (const store of [window.localStorage, window.sessionStorage]) {
    try {
      const raw = store.getItem(CACHE_KEY)
      if (!raw) continue
      const { value, at } = JSON.parse(raw)
      if (value && Date.now() - at < CACHE_TTL_MS) return value
      store.removeItem(CACHE_KEY)
    } catch {
      /* зіпсований запис — ігноруємо */
    }
  }
  return ''
}

/** Витягує tgWebAppData з фрагмента адреси.
 *
 * Telegram кладе туди рядок виду
 *   #tgWebAppData=query_id=..&user=..&hash=..&tgWebAppVersion=9.6&tgWebAppPlatform=android
 * причому роздільники всередині tgWebAppData не закодовані. Тому значення
 * тягнеться до першого наступного параметра tgWebApp*, а не до першого «&».
 */
function fromHash() {
  const hash = window.location.hash.slice(1)
  const marker = 'tgWebAppData='
  const at = hash.indexOf(marker)
  if (at === -1) return ''

  const tail = hash.slice(at + marker.length)
  const stop = tail.search(/&tgWebApp[A-Z]/)
  let value = stop === -1 ? tail : tail.slice(0, stop)

  // Частина клієнтів кодує значення цілком, частина — ні
  if (!value.includes('hash=')) {
    try {
      value = decodeURIComponent(value)
    } catch {
      /* лишаємо як є */
    }
  }
  return value
}

/** Підписаний рядок, яким бекенд упізнає покупця.
 *
 * Читається щоразу, а не один раз при завантаженні модуля: SDK стирає
 * фрагмент з адреси відразу після старту, тож після перезавантаження
 * сторінки перше джерело порожніє. Значення кешується в sessionStorage —
 * воно живе рівно стільки, скільки вкладка, і не потрапляє на диск.
 */
export function getInitData() {
  const fromSdk = tg?.initData
  if (fromSdk) {
    cacheWrite(fromSdk)
    return fromSdk
  }

  const hashed = fromHash()
  if (hashed) {
    cacheWrite(hashed)
    return hashed
  }

  return cacheRead()
}

/** Які параметри запуску Telegram поклав у адресу.
 *
 * Лише імена ключів, без значень: підпис і дані користувача у звіт
 * потрапляти не мають. Наявність або відсутність tgWebAppData тут —
 * головна ознака того, у якому контексті відкрито застосунок.
 */
export function launchParamNames() {
  const hash = window.location.hash.slice(1)
  if (!hash) return []
  return [...new Set(
    hash
      .split('&')
      .map((pair) => pair.split('=')[0])
      .filter((name) => name.startsWith('tgWebApp')),
  )]
}

/** Звідки саме взялися дані — потрібно для екрана діагностики. */
/** Параметр startapp: за ним відкриваємо потрібний екран одразу.
 *
 * Кнопка «Відкрити чат» у боті веде на /app/?chat=7, а пряме посилання
 * Mini App передає те саме через tgWebAppStartParam. Перевіряємо обидва.
 */
export function startTarget() {
  const fromQuery = new URLSearchParams(window.location.search).get('chat')
  if (fromQuery && /^\d+$/.test(fromQuery)) return { screen: 'chat', orderId: Number(fromQuery) }

  const param = tg?.initDataUnsafe?.start_param || ''
  const match = /^chat[-_](\d+)$/.exec(param)
  if (match) return { screen: 'chat', orderId: Number(match[1]) }

  return null
}


export function initDataSource() {
  if (tg?.initData) return 'SDK'
  if (fromHash()) return 'адреса сторінки'
  if (cacheRead()) return 'кеш пристрою'
  return 'немає'
}

export const isTelegram = Boolean(tg?.initData || fromHash() || tg?.platform)

export function ready() {
  if (!tg) return
  tg.ready()
  tg.expand()
  // Свайп вниз закриває вікно — при прокрутці каталогу це дратує
  tg.disableVerticalSwipes?.()
}

/** Розбирає #rrggbb у три числа. Повертає null на будь-чому іншому. */
function parseHex(value) {
  const match = /^#?([0-9a-f]{6})$/i.exec(String(value || '').trim())
  if (!match) return null
  const n = parseInt(match[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function toHex([r, g, b]) {
  return '#' + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v)))
    .toString(16).padStart(2, '0')).join('')
}

/** Колір підкладки, якщо Telegram його не надіслав.
 *
 *  Зсуваємо фон на 8% у бік тексту: на світлій темі підкладка стає трохи
 *  темнішою за фон, на темній — трохи світлішою. В обох випадках текст
 *  лишається читабельним, бо рухаємось саме до його кольору.
 */
function deriveSecondary(bg, text) {
  const a = parseHex(bg)
  const b = parseHex(text)
  if (!a || !b) return null
  return toHex(a.map((channel, i) => channel + (b[i] - channel) * 0.08))
}

/** Наскільки два кольори різняться на око: 0 — однакові, 1 — чорне з білим.
 *
 *  Потрібно для одного рішення: чи можна довіряти підкладці, яку надіслав
 *  клієнт. Тема в Telegram налаштовується користувачем, і серед
 *  користувацьких тем трапляються такі, де колір панелей майже збігається
 *  з кольором тексту. Наш застосунок у такій темі виглядав би зламаним,
 *  хоч зламана в ній саме тема.
 */
function contrast(first, second) {
  const a = parseHex(first)
  const b = parseHex(second)
  if (!a || !b) return 1
  const luminance = ([r, g, blue]) => (0.2126 * r + 0.7152 * g + 0.0722 * blue) / 255
  return Math.abs(luminance(a) - luminance(b))
}

/** Кольори з клієнта користувача: міні-апп має збігатися з його темою.
 *
 *  Застосовуємо все разом або нічого. Раніше кожна змінна ставилась
 *  окремо, і цього було досить, щоб зламати вигляд: клієнти зі світлою
 *  темою часто не надсилають secondary_bg_color. Тоді текст ставав
 *  темним, підкладка полів лишалась нашою темною за замовчуванням — і
 *  введений текст ставав невидимим.Половина теми гірша за жодну.
 */
export function applyTheme() {
  if (!tg) return
  const root = document.documentElement
  const p = tg.themeParams || {}

  // Фон і текст — основа. Без них решта не має сенсу: змішувати чужий
  // текст із нашим фоном і означає отримати невидимі поля.
  const bg = parseHex(p.bg_color) ? p.bg_color : null
  const text = parseHex(p.text_color) ? p.text_color : null
  if (!bg || !text) {
    root.dataset.scheme = tg.colorScheme || 'dark'
    return
  }

  // Підкладка полів — єдиний колір, який ми перевіряємо, а не беремо на
  // віру. Решта тільки псує вигляд; ця — робить введений текст
  // невидимим, і людина бачить не «негарно», а «зламано».
  const fieldBackground = (sent, background, foreground) => {
    const own = deriveSecondary(background, foreground)
    if (!sent || !parseHex(sent)) return own
    return contrast(sent, foreground) < 0.2 ? own : sent
  }

  const map = {
    '--tg-bg': bg,
    '--tg-text': text,
    '--tg-hint': p.hint_color || deriveSecondary(text, bg),
    '--tg-link': p.link_color,
    '--tg-button': p.button_color,
    '--tg-button-text': p.button_text_color,
    '--tg-secondary-bg': fieldBackground(p.secondary_bg_color, bg, text),
  }
  for (const [name, value] of Object.entries(map)) {
    if (value) root.style.setProperty(name, value)
  }
  root.dataset.scheme = tg.colorScheme || 'dark'
}

// Експортуємо для тестів: логіка кольорів надто дорога, щоб перевіряти
// її очима на живому пристрої.
export const _theme = { parseHex, toHex, deriveSecondary, contrast }

export function onThemeChange(handler) {
  tg?.onEvent?.('themeChanged', handler)
  return () => tg?.offEvent?.('themeChanged', handler)
}

/** Головна кнопка Telegram — нативний спосіб показати основну дію. */
export function mainButton({ text, visible = true, loading = false, onClick }) {
  const b = tg?.MainButton
  if (!b) return () => {}
  if (!visible) {
    b.hide()
    return () => {}
  }
  b.setText(text)
  b.show()
  loading ? b.showProgress(true) : b.hideProgress()
  if (onClick) {
    b.onClick(onClick)
    return () => b.offClick(onClick)
  }
  return () => {}
}

export function hideMainButton() {
  tg?.MainButton?.hide()
}

export function backButton(onClick) {
  const b = tg?.BackButton
  if (!b) return () => {}
  if (!onClick) {
    b.hide()
    return () => {}
  }
  b.show()
  b.onClick(onClick)
  return () => {
    b.offClick(onClick)
    b.hide()
  }
}

export function haptic(style = 'light') {
  tg?.HapticFeedback?.impactOccurred?.(style)
}

export function notify(type = 'success') {
  tg?.HapticFeedback?.notificationOccurred?.(type)
}

export function close() {
  tg?.close()
}

export function openLink(url) {
  tg?.openTelegramLink ? tg.openTelegramLink(url) : window.open(url, '_blank')
}

/** Нативний діалог замість window.confirm — той у Telegram виглядає чужим. */
export function confirm(message) {
  return new Promise((resolve) => {
    if (tg?.showConfirm) tg.showConfirm(message, resolve)
    else resolve(window.confirm(message))
  })
}

export function alert(message) {
  if (tg?.showAlert) tg.showAlert(message)
  else window.alert(message)
}
