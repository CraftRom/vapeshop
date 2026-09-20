/** Обгортка над Telegram WebApp SDK.
 *
 * Уся робота з window.Telegram зібрана тут, щоб застосунок не падав,
 * якщо його відкрити у звичайному браузері — там SDK просто немає,
 * і кожна функція тихо стає порожньою.
 */
const webApp = () => window.Telegram?.WebApp

const CACHE_KEY = 'tgInitData'
const BRIDGE_PARAM = 'elfarInitData'
let lastInitDataSource = ''
// Android інколи вивантажує WebView і повертає вже обрізану адресу. Для
// короткого self-heal тримаємо підпис і в localStorage, але лише 15 хвилин:
// довгий persistent cache перетворювався б на фактичну повторно придатну
// сесію Telegram і міг би пережити перемикання акаунта на тому самому ПК.
const CACHE_TTL_MS = 15 * 60 * 1000

const LEGACY_HOSTS = new Map([
  ['www.elfar.pp.ua', 'elfar.pp.ua'],
])

/** Повертає канонічну адресу для історичного host, не гублячи query/hash.
 *
 * Telegram додає авторизаційні параметри саме до URL Mini App. Якщо просто
 * відправити користувача на /app/ новим рядком, можна втратити launch data.
 * Тому міняємо лише hostname у поточній адресі: шлях, query і fragment
 * лишаються байт-у-байт.
 */
export function legacyHostRedirectUrl(initData = '') {
  const target = LEGACY_HOSTS.get(window.location.hostname.toLowerCase())
  if (!target) return ''
  const url = new URL(window.location.href)
  url.hostname = target
  url.protocol = 'https:'

  // Підпис, який уже встиг з'явитися в SDK на legacy-host, не можна
  // залишати лише в пам'яті сторінки: location.replace створить новий
  // document на іншому origin і Telegram не зобов'язаний передати його
  // вдруге. Передаємо його одноразово у fragment — fragment не йде в HTTP
  // запит і після читання на canonical-host одразу прибирається з URL.
  if (initData) {
    const encoded = encodeURIComponent(initData)
    const hash = String(url.hash || '').replace(/^#/, '')
    const withoutOldBridge = hash
      .replace(new RegExp(`(^|&)${BRIDGE_PARAM}=[^&]*`, 'g'), '$1')
      .replace(/^&|&$/g, '')
      .replace(/&&+/g, '&')
    url.hash = `${withoutOldBridge}${withoutOldBridge ? '&' : ''}${BRIDGE_PARAM}=${encoded}`
  }
  return url.toString()
}

function cacheWrite(value) {
  const payload = JSON.stringify({
    value,
    at: Date.now(),
    userId: signedUserId(value),
  })
  for (const store of [window.localStorage, window.sessionStorage]) {
    try {
      store.setItem(CACHE_KEY, payload)
    } catch {
      /* приватний режим або переповнення — просто пропускаємо */
    }
  }
}

function cacheRead() {
  const currentUserId = String(webApp()?.initDataUnsafe?.user?.id || '')
  for (const store of [window.sessionStorage, window.localStorage]) {
    try {
      const raw = store.getItem(CACHE_KEY)
      if (!raw) continue
      const { value, at, userId = '' } = JSON.parse(raw)
      const fresh = value && Number.isFinite(at) && Date.now() - at < CACHE_TTL_MS
      const sameUser = !currentUserId || !userId || currentUserId === String(userId)
      if (fresh && sameUser) return value
      store.removeItem(CACHE_KEY)
    } catch {
      try { store.removeItem(CACHE_KEY) } catch { /* ignore */ }
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
function fromParamString(raw) {
  const source = String(raw || '').replace(/^[?#]/, '')
  const marker = 'tgWebAppData='
  const at = source.indexOf(marker)
  if (at === -1) return ''

  const tail = source.slice(at + marker.length)
  const stop = tail.search(/&tgWebApp[A-Z]/)
  let value = stop === -1 ? tail : tail.slice(0, stop)

  // Частина клієнтів кодує значення цілком, частина — ні.
  // decodeURIComponent безпечний лише як fallback: якщо рядок уже
  // розкодований, повторне декодування може пошкодити user JSON.
  if (!value.includes('hash=')) {
    try {
      value = decodeURIComponent(value)
    } catch {
      /* лишаємо як є */
    }
  }
  return value
}

function fromBridge() {
  const source = String(window.location.hash || '').replace(/^#/, '')
  const match = new RegExp(`(?:^|&)${BRIDGE_PARAM}=([^&]*)`).exec(source)
  if (!match?.[1]) return ''
  try {
    return decodeURIComponent(match[1])
  } catch {
    return ''
  }
}

function stripBridgeFromUrl() {
  const source = String(window.location.hash || '').replace(/^#/, '')
  if (!source.includes(`${BRIDGE_PARAM}=`)) return
  const cleaned = source
    .replace(new RegExp(`(^|&)${BRIDGE_PARAM}=[^&]*`, 'g'), '$1')
    .replace(/^&|&$/g, '')
    .replace(/&&+/g, '&')
  const next = `${window.location.pathname}${window.location.search}${cleaned ? `#${cleaned}` : ''}`
  try { window.history.replaceState(null, '', next) } catch { /* WebView може заборонити */ }
}

function signedUserId(value) {
  try {
    const raw = new URLSearchParams(value).get('user')
    if (!raw) return ''
    const parsed = JSON.parse(raw)
    return String(parsed?.id || '')
  } catch {
    return ''
  }
}

function fromHash() {
  return fromParamString(window.location.hash)
}

function fromSearch() {
  return fromParamString(window.location.search)
}

/** Підписаний рядок, яким бекенд упізнає покупця.
 *
 * Читається щоразу, а не один раз при завантаженні модуля: SDK стирає
 * фрагмент з адреси відразу після старту, тож після перезавантаження
 * сторінки перше джерело порожніє. Значення кешується в sessionStorage —
 * воно живе рівно стільки, скільки вкладка, і не потрапляє на диск.
 */
export function getInitData() {
  const fromSdk = webApp()?.initData
  if (fromSdk) {
    lastInitDataSource = 'SDK'
    cacheWrite(fromSdk)
    return fromSdk
  }

  const hashed = fromHash()
  if (hashed) {
    lastInitDataSource = 'fragment URL'
    cacheWrite(hashed)
    return hashed
  }

  const bridged = fromBridge()
  if (bridged) {
    lastInitDataSource = 'legacy bridge'
    cacheWrite(bridged)
    stripBridgeFromUrl()
    return bridged
  }

  // Деякі оболонки/проксі Telegram переносять launch-параметри з fragment
  // у query string. Це не типовий шлях, але відкидати валідний підпис лише
  // через місце в URL немає сенсу.
  const searched = fromSearch()
  if (searched) {
    lastInitDataSource = 'query URL'
    cacheWrite(searched)
    return searched
  }

  const cached = cacheRead()
  if (cached) lastInitDataSource = 'кеш пристрою'
  return cached
}

/** Які параметри запуску Telegram поклав у адресу.
 *
 * Лише імена ключів, без значень: підпис і дані користувача у звіт
 * потрапляти не мають. Наявність або відсутність tgWebAppData тут —
 * головна ознака того, у якому контексті відкрито застосунок.
 */
export function launchParamNames() {
  const names = []
  for (const raw of [window.location.search, window.location.hash]) {
    const value = String(raw || '').replace(/^[?#]/, '')
    if (!value) continue
    names.push(...value
      .split('&')
      .map((pair) => pair.split('=')[0])
      .filter((name) => name.startsWith('tgWebApp')))
  }
  return [...new Set(names)]
}

/** Звідки саме взялися дані — потрібно для екрана діагностики. */
/** Параметр startapp: за ним відкриваємо потрібний екран одразу.
 *
 * Кнопка «Відкрити чат» у боті веде у Named Mini App зі startapp=chat_7,
 * Mini App передає те саме через tgWebAppStartParam. Перевіряємо обидва.
 */
export function startTarget() {
  const fromQuery = new URLSearchParams(window.location.search).get('chat')
  if (fromQuery && /^\d+$/.test(fromQuery)) return { screen: 'chat', orderId: Number(fromQuery) }

  const param = webApp()?.initDataUnsafe?.start_param || ''
  const match = /^chat[-_](\d+)$/.exec(param)
  if (match) return { screen: 'chat', orderId: Number(match[1]) }

  return null
}


export function initDataSource() {
  if (webApp()?.initData) return 'SDK'
  if (fromHash()) return 'fragment URL'
  if (fromBridge()) return 'legacy bridge'
  if (fromSearch()) return 'query URL'
  if (lastInitDataSource) return lastInitDataSource
  if (cacheRead()) return 'кеш пристрою'
  return 'немає'
}

export function isTelegramContext() {
  const current = window.Telegram?.WebApp
  return Boolean(current?.initData || fromHash() || fromBridge() || fromSearch() || current?.platform)
}

/** Telegram WebView інколи створює SDK раніше, ніж заповнює initData.
 * Даємо клієнту короткий шанс завершити ініціалізацію замість миттєвої
 * помилки на білому екрані.
 */
export async function waitForInitData(timeoutMs = 1500) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const value = getInitData()
    if (value) return value
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  return getInitData()
}

export function ready() {
  if (!webApp()) return
  webApp().ready()
  webApp().expand()
  // Свайп вниз закриває вікно — при прокрутці каталогу це дратує
  webApp()?.disableVerticalSwipes?.()
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
  if (!webApp()) return
  const root = document.documentElement
  const p = webApp()?.themeParams || {}

  // Фон і текст — основа. Без них решта не має сенсу: змішувати чужий
  // текст із нашим фоном і означає отримати невидимі поля.
  const bg = parseHex(p.bg_color) ? p.bg_color : null
  const text = parseHex(p.text_color) ? p.text_color : null
  if (!bg || !text) {
    root.dataset.scheme = webApp()?.colorScheme || 'dark'
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
  root.dataset.scheme = webApp()?.colorScheme || 'dark'
}

// Експортуємо для тестів: логіка кольорів надто дорога, щоб перевіряти
// її очима на живому пристрої.
export const _theme = { parseHex, toHex, deriveSecondary, contrast }

export function onThemeChange(handler) {
  webApp()?.onEvent?.('themeChanged', handler)
  return () => webApp()?.offEvent?.('themeChanged', handler)
}

/** Головна кнопка Telegram — нативний спосіб показати основну дію. */
export function mainButton({ text, visible = true, loading = false, onClick }) {
  const b = webApp()?.MainButton
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
  webApp()?.MainButton?.hide()
}

// Поточна дія системної кнопки «назад» і ознака того, що обробник уже
// прив'язаний. Обидва — на весь час життя застосунку.
let backAction = null
let backBound = false

/** Системна кнопка «назад» Telegram.
 *
 * Обробник прив'язується РІВНО ОДИН РАЗ, а міняється лише дія, яку він
 * викликає. Раніше на кожен екран вішався новий обробник, а старий
 * знімався через offClick — і це працювало доти, доки offClick працює.
 * Там, де він мовчки нічого не робить, обробники накопичуються, і
 * натискання виконує найперший із них: дію екрана, з якого пішли пів
 * години тому. Ззовні це виглядає як «кнопка не працює» — саме так, як
 * описано: назад не веде нікуди, і застосунок доводиться закривати
 * разом із Telegram.
 *
 * Один обробник на застосунок цю можливість прибирає повністю: нема чому
 * накопичуватись.
 */
export function backButton(onClick) {
  const b = webApp()?.BackButton
  if (!b) return () => {}

  if (!backBound) {
    b.onClick(() => backAction?.())
    backBound = true
  }

  backAction = onClick || null
  if (onClick) b.show()
  else b.hide()

  // Прибирати нічого: наступний виклик замінить дію, а обробник лишається
  // той самий. Повертаємо порожню функцію, щоб виклик у ефекті React не
  // довелося переписувати.
  return () => {}
}

export function haptic(style = 'light') {
  webApp()?.HapticFeedback?.impactOccurred?.(style)
}

export function notify(type = 'success') {
  webApp()?.HapticFeedback?.notificationOccurred?.(type)
}

/** Запит дозволу поділитися номером через Telegram.
 *
 * Важливо: WebApp.requestContact() НЕ повертає номер у JavaScript. Callback
 * повідомляє лише, чи користувач погодився. Сам контакт Telegram надсилає
 * боту окремим update; backend зберігає його в профілі, а Mini App читає
 * номер через власний API. У старих клієнтах методу немає — кнопку тоді
 * не показуємо.
 */
export function requestContact() {
  return new Promise((resolve) => {
    const app = webApp()
    if (typeof app?.requestContact !== 'function') {
      resolve(false)
      return
    }

    let settled = false
    let timer = null
    let callbackGrace = null
    const finish = (value) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      if (callbackGrace) clearTimeout(callbackGrace)
      try { app.offEvent?.('contactRequested', onEvent) } catch { /* noop */ }
      resolve(Boolean(value))
    }
    const onEvent = (event) => {
      if (event?.status === 'sent') finish(true)
      else if (event?.status === 'cancelled') finish(false)
    }

    try { app.onEvent?.('contactRequested', onEvent) } catch { /* callback still works */ }
    // Деякі клієнти Telegram викликають callback і подію не синхронно.
    // Даємо події достатньо часу, але не тримаємо кнопку вічно.
    timer = setTimeout(() => finish(false), 20000)

    try {
      app.requestContact((granted) => {
        if (granted === true) {
          finish(true)
          return
        }
        // Не завершуємо false миттєво: на частині клієнтів callback може
        // прийти раніше за contactRequested:sent. Коротке вікно прибирає
        // цю гонку без помітної затримки при реальній відмові.
        callbackGrace = setTimeout(() => finish(false), 1200)
      })
    } catch {
      finish(false)
    }
  })
}

export function canRequestContact() {
  return typeof webApp()?.requestContact === 'function'
}

export function close() {
  webApp()?.close()
}

export function openLink(url) {
  webApp()?.openTelegramLink ? webApp().openTelegramLink(url) : window.open(url, '_blank')
}

/** Нативний діалог замість window.confirm — той у Telegram виглядає чужим. */
export function confirm(message) {
  return new Promise((resolve) => {
    if (webApp()?.showConfirm) webApp().showConfirm(message, resolve)
    else resolve(window.confirm(message))
  })
}

export function alert(message) {
  return new Promise((resolve) => {
    const app = webApp()
    if (app?.showAlert) {
      let settled = false
      const finish = () => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        resolve()
      }
      // У кількох клієнтах callback showAlert може не повернутися після
      // успішного checkout. Діалог не має блокувати success-flow назавжди.
      const timer = setTimeout(finish, 3500)
      try {
        app.showAlert(message, finish)
      } catch {
        finish()
      }
      return
    }
    window.alert(message)
    resolve()
  })
}
