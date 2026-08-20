/** Обгортка над Telegram WebApp SDK.
 *
 * Уся робота з window.Telegram зібрана тут, щоб застосунок не падав,
 * якщо його відкрити у звичайному браузері — там SDK просто немає,
 * і кожна функція тихо стає порожньою.
 */
const tg = window.Telegram?.WebApp

const CACHE_KEY = 'tgInitData'

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
    try {
      sessionStorage.setItem(CACHE_KEY, fromSdk)
    } catch {
      /* приватний режим — просто не кешуємо */
    }
    return fromSdk
  }

  const hashed = fromHash()
  if (hashed) {
    try {
      sessionStorage.setItem(CACHE_KEY, hashed)
    } catch {
      /* те саме */
    }
    return hashed
  }

  try {
    return sessionStorage.getItem(CACHE_KEY) || ''
  } catch {
    return ''
  }
}

/** Звідки саме взялися дані — потрібно для екрана діагностики. */
export function initDataSource() {
  if (tg?.initData) return 'SDK'
  if (fromHash()) return 'адреса сторінки'
  try {
    if (sessionStorage.getItem(CACHE_KEY)) return 'кеш вкладки'
  } catch {
    /* нічого */
  }
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

/** Кольори з клієнта користувача: міні-апп має збігатися з його темою. */
export function applyTheme() {
  if (!tg) return
  const root = document.documentElement
  const p = tg.themeParams || {}
  const map = {
    '--tg-bg': p.bg_color,
    '--tg-text': p.text_color,
    '--tg-hint': p.hint_color,
    '--tg-link': p.link_color,
    '--tg-button': p.button_color,
    '--tg-button-text': p.button_text_color,
    '--tg-secondary-bg': p.secondary_bg_color,
  }
  for (const [name, value] of Object.entries(map)) {
    if (value) root.style.setProperty(name, value)
  }
  root.dataset.scheme = tg.colorScheme || 'dark'
}

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
