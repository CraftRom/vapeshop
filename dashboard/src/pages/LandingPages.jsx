import { useEffect, useMemo, useRef, useState } from 'react'
import { api, isAdmin } from '../api'
import ImageField from '../components/ImageField'
import { Empty, ErrorBar, Field, Loading, Modal, useToast } from '../components/ui'

const DEFAULT_CONTENT = {
  background_image: '', logo_image: '', eyebrow: '',
  title: 'Телеграм канал шалених знижок 🔥',
  promo_label: 'Ваш персональний промокод:', promo_code: 'PROMO2026',
  description: 'Отримайте 7% знижки, скориставшись ним під час замовлення.',
  validity_text: 'Не зволікайте — промокод активний лише 1 добу після отримання.',
  button_text: 'ПЕРЕЙТИ', button_url: 'https://t.me/', footer_text: '',
}
const DEFAULT_SEO = {
  title: 'Акційна пропозиція',
  description: 'Отримайте персональний промокод та скористайтеся спеціальною пропозицією.',
  keywords: '', canonical_url: '',
  robots: 'index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1',
  og_title: '', og_description: '', og_image: '', og_locale: 'uk_UA', site_name: '',
  schema_name: '', schema_description: '',
}

const DEFAULT_GOOGLE = {
  enabled: false,
  mode: 'google_tag',
  google_tag_id: '',
  gtm_container_id: '',
  ads_conversion_id: '',
  ads_conversion_label: '',
  search_console_verification: '',
  consent_mode: 'banner',
}

const GOOGLE_HELP = {
  enabled: 'Увімкніть, коли хочете передавати перегляди та події цієї промо-сторінки в Google. Search Console verification може працювати окремо навіть без аналітики.',
  mode: 'Google tag — простіший варіант для GA4/Google Ads. Google Tag Manager — контейнер для складніших сценаріїв і керування тегами без повторного редагування сторінки.',
  google_tag_id: 'ID Google tag / GA4. Приклади: G-XXXXXXXXXX, GT-XXXXXXX або AW-123456789. Скрипт gtag.js підключається лише один раз.',
  gtm_container_id: 'ID контейнера Google Tag Manager у форматі GTM-XXXXXXX. У цьому режимі сторінка передає подію promo_cta_click у dataLayer, а потрібні теги налаштовуються у GTM.',
  ads_conversion_id: 'Conversion ID Google Ads у форматі AW-123456789. Використовується для прямої конверсії лише в режимі Google tag.',
  ads_conversion_label: 'Conversion Label конкретної дії в Google Ads. Разом з Conversion ID формує send_to для події conversion.',
  search_console_verification: 'Тільки значення content з meta-тегу google-site-verification. Після публікації Google Search Console зможе підтвердити володіння доменом через HTML meta tag.',
  consent_mode: 'Consent Mode v2 керує analytics_storage, ad_storage, ad_user_data і ad_personalization. Рекомендований варіант — вбудований банер: до вибору користувача зберігання заборонене.',
}


const SEO_HELP = {
  title: { title: 'Meta title', text: 'Основний заголовок сторінки для пошукових систем і вкладки браузера. Допомагає Google зрозуміти тему сторінки та часто використовується як синє посилання у результатах пошуку. Має бути конкретним, природним і відрізнятися від інших промо-сторінок. Рекомендовано приблизно 50–68 символів.' },
  canonical_url: { title: 'Canonical URL', text: 'Канонічна адреса повідомляє пошуковим системам, яку URL-версію сторінки вважати основною. Захищає від дублювання сигналів між варіантами URL, UTM-посиланнями або технічними копіями. Для звичайної промо-сторінки це її HTTPS-адреса.' },
  description: { title: 'Meta description', text: 'Короткий опис змісту сторінки. Не є прямим фактором ранжування Google, але часто використовується у сніпеті пошуку й може впливати на CTR. Генератор формує його з реальної пропозиції, умов і бренду, без вигаданих переваг.' },
  keywords: { title: 'Keywords', text: 'Список тематичних фраз для сумісності з іншими системами, внутрішніми інструментами та деякими пошуковиками. Google meta keywords практично не використовує для ранжування, тому поле не повинно перетворюватися на спам. Генератор бере лише слова з фактичного контенту сторінки.' },
  robots: { title: 'Robots', text: 'Керує індексацією та способом показу контенту пошуковими роботами. index,follow дозволяє індексувати сторінку й переходити за посиланнями; max-image-preview:large дозволяє великі прев’ю зображень; max-snippet:-1 і max-video-preview:-1 не обмежують розмір доступних сніпетів.' },
  og_locale: { title: 'Open Graph locale', text: 'Мова й регіон Open Graph-даних. Використовується соцмережами та месенджерами під час формування картки посилання. Для української сторінки стандартне значення — uk_UA.' },
  og_title: { title: 'Open Graph title', text: 'Заголовок картки при поширенні посилання у Telegram, Facebook, Discord та інших сервісах, що читають Open Graph. Може бути трохи рекламнішим за Meta title, але повинен точно відповідати змісту сторінки.' },
  og_description: { title: 'Open Graph description', text: 'Опис для картки посилання у соцмережах і месенджерах. Дає людині контекст ще до відкриття сторінки. Генератор створює окрему варіацію, щоб вона не дублювала Meta description слово в слово.' },
  site_name: { title: 'Site name', text: 'Назва бренду або сайту, яка може відображатися у картці Open Graph і допомагає ідентифікувати джерело. Генератор визначає її з домену та внутрішньої назви сторінки.' },
  og_image: { title: 'OG / social image', text: 'Головне зображення для прев’ю посилання в соцмережах і месенджерах. Воно має бути локальним файлом із /media/. Якщо спеціальне зображення не задано, генератор використовує вибраний фон або логотип сторінки.' },
  schema_name: { title: 'Schema name', text: 'Назва сторінки у структурованих даних Schema.org / JSON-LD. Допомагає пошуковим системам машинно прочитати сутність сторінки та зв’язати її назву з URL, описом і основним зображенням.' },
  schema_description: { title: 'Schema description', text: 'Розгорнутий машинозчитуваний опис для JSON-LD WebPage. Він не показується як звичайний текст на сторінці, але додає контекст пошуковим системам. Генератор формує його з фактичного промо-тексту та умов.' },
}

function SeoLabel({ field }) {
  const item = SEO_HELP[field]
  return <span className="seo-help-label"><span>{item.title}</span><span className="seo-help" tabIndex="0" role="button" aria-label={`Довідка: ${item.title}`}><span aria-hidden="true">?</span><span className="seo-help-tooltip" role="tooltip"><strong>{item.title}</strong>{item.text}</span></span></span>
}

const newForm = () => ({ name: 'Нова промо-сторінка', domain: '', content: { ...DEFAULT_CONTENT }, seo: { ...DEFAULT_SEO }, google: { ...DEFAULT_GOOGLE } })

function normalized(page) {
  if (!page) return newForm()
  return {
    name: page.name || '', domain: page.domain || '',
    content: { ...DEFAULT_CONTENT, ...(page.draft?.content || {}) },
    seo: { ...DEFAULT_SEO, ...(page.draft?.seo || {}) },
    google: { ...DEFAULT_GOOGLE, ...(page.draft?.google || {}) },
  }
}

function Metric({ label, value, sub }) {
  return <div className="card metric"><div className="label">{label}</div><div className="value">{value}</div>{sub && <div className="sub">{sub}</div>}</div>
}

function CopyValue({ value }) {
  if (!value) return <span className="faint">—</span>
  const copy = async () => { try { await navigator.clipboard.writeText(value) } catch {} }
  return <span className="promo-dns-copy"><code>{value}</code><button type="button" className="btn ghost promo-dns-copy-btn" onClick={copy}>Копіювати</button></span>
}


function domainCheckSummary(state) {
  const dnsReady = state?.dns?.pointsHere === true
  const dnsKnown = !!state?.dns
  const routeReady = !!state?.routePresent
  const tlsReady = !!state?.tls?.present
  const productionReady = !!state?.active
  const dnsLabel = dnsReady ? 'DNS веде на VPS' : dnsKnown ? (state?.dns?.ok ? 'DNS веде на іншу адресу' : 'DNS ще не готовий') : 'Очікуємо первинну перевірку'
  const routeLabel = routeReady ? 'Маршрут створено' : 'Маршрут ще не створено'
  const tlsLabel = tlsReady ? `TLS активний${state?.tls?.expiresAt ? ` до ${new Date(state.tls.expiresAt).toLocaleDateString('uk-UA')}` : ''}` : 'TLS ще не активний'
  const productionLabel = productionReady ? 'Сайт доступний' : 'Production ще не готовий'
  const overall = productionReady ? 'ready' : (dnsReady || routeReady || tlsReady ? 'progress' : 'waiting')
  return {
    overall,
    steps: [
      { key: 'dns', title: 'DNS', status: dnsReady ? 'ok' : (dnsKnown ? 'warn' : 'checking'), text: dnsLabel },
      { key: 'route', title: 'Маршрут', status: routeReady ? 'ok' : (dnsReady ? 'progress' : 'waiting'), text: routeLabel },
      { key: 'tls', title: 'TLS / HTTPS', status: tlsReady ? 'ok' : (routeReady ? 'progress' : 'waiting'), text: tlsLabel },
      { key: 'prod', title: 'Production', status: productionReady ? 'ok' : ((tlsReady || routeReady) ? 'progress' : 'waiting'), text: productionLabel },
    ],
  }
}

function prettyCheckState(refreshing, state, autoRefresh) {
  if (refreshing) return 'Виконуємо перевірку…'
  if (state?.active) return 'Готово до роботи'
  if (state?.tls?.present) return 'TLS активний, завершуємо перевірки'
  if (state?.routePresent) return 'Маршрут активовано, очікуємо HTTPS'
  if (state?.dns?.pointsHere === true) return 'DNS готовий, можна підключати домен'
  if (state?.dns?.ok) return 'DNS веде на іншу адресу'
  if (autoRefresh) return 'Автоматично перевіряємо DNS'
  return 'Очікуємо коректний DNS'
}


function promoRuntimeInfo(page, state) {
  if (!page?.isPublished) return { tone: 'draft', badge: 'Чернетка', text: 'Ще не опубліковано' }
  if (!state) return { tone: 'checking', badge: 'Перевіряємо', text: 'Оновлюємо стан сторінки' }
  if (state.error) return { tone: 'problem', badge: 'Проблема', text: 'Не вдалося отримати стан сторінки' }
  const live = state.live || {}
  if (live.status === 'up') return { tone: 'ok', badge: 'Працює', text: 'Сайт доступний для відвідувачів' }
  if (live.status === 'blocked') return { tone: 'problem', badge: 'Обмежено', text: live.message || 'Доступ до сайту обмежено' }
  if (live.status === 'down' || live.status === 'error' || live.status === 'slow') return { tone: 'problem', badge: live.label || 'Недоступний', text: live.message || 'Сайт не відкривається як слід' }
  if (state.routePresent && !state.tls?.present) return { tone: 'progress', badge: 'Підключаємо', text: 'Готуємо HTTPS і публічний доступ' }
  if (!state.routePresent && state.dns?.pointsHere) return { tone: 'progress', badge: 'Готово до підключення', text: 'DNS уже налаштовано, можна запускати сайт' }
  if (state.dns?.propagating) return { tone: 'progress', badge: 'Поширюється', text: 'Чекаємо оновлення DNS у мережі' }
  if (state.dns?.ok && state.dns?.pointsHere === false) return { tone: 'problem', badge: 'Інша адреса', text: 'Домен веде не на цей сервер' }
  if (live.status === 'disabled') return { tone: 'draft', badge: 'Вимкнено', text: live.message || 'Сторінка вимкнена' }
  return { tone: 'checking', badge: live.label || 'Перевіряємо', text: live.message || 'Оновлюємо стан сторінки' }
}

function deployReadiness(state) {
  if (!state) return { tone: 'waiting', title: 'Очікуємо перевірку', text: 'Щойно ви відкрили цей розділ — панель починає перевіряти домен та доступність сайту.' }
  if (state.live?.status === 'up') return { tone: 'ok', title: 'Сайт працює', text: 'Промо-сторінка доступна для відвідувачів. За потреби можна просто відкрити сайт або оновити контент.' }
  if (!state.page?.published) return { tone: 'draft', title: 'Спершу опублікуйте сторінку', text: 'Поки сторінка не опублікована, відвідувачі не побачать її навіть при готовому домені.' }
  if (state.dns?.ok && state.dns?.pointsHere === false) return { tone: 'problem', title: 'Домен веде не туди', text: 'Зараз домен веде на іншу адресу. Виправте DNS-запис і дочекайтеся поширення.' }
  if (state.dns?.propagating) return { tone: 'progress', title: 'DNS ще оновлюється', text: 'Частина мереж уже бачить правильну адресу, але ще не всі. Панель перевірятиме це автоматично.' }
  if (state.routePresent && !state.tls?.present) return { tone: 'progress', title: 'Підключаємо захищений доступ', text: 'Маршрут уже створено. Зараз чекаємо HTTPS-сертифікат або завершення перевірки.' }
  if (state.routePresent && state.tls?.present && state.live?.status !== 'up') return { tone: 'progress', title: 'Майже готово', text: state.live?.message || 'HTTPS уже активний, завершуємо перевірку доступності сайту.' }
  if (state.dns?.pointsHere) return { tone: 'ready', title: 'Можна запускати сайт', text: 'DNS налаштовано правильно. Наступний крок — підключити домен і видати HTTPS.' }
  return { tone: 'waiting', title: 'Підготуйте домен', text: 'Почніть із DNS-записів нижче. Коли домен почне вести на цей сервер, запуск стане доступним.' }
}

export default function LandingPages() {
  const notify = useToast()
  const [pages, setPages] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [form, setForm] = useState(newForm())
  const [tab, setTab] = useState('content')
  const [stats, setStats] = useState(null)
  const [domainState, setDomainState] = useState(null)
  const [domainBusy, setDomainBusy] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [seoBusy, setSeoBusy] = useState(false)
  const [cfConfig, setCfConfig] = useState({ configured: false })
  const [cfToken, setCfToken] = useState('')
  const [cfBusy, setCfBusy] = useState(false)
  const canConfigureCloudflare = isAdmin()
  const [domainRefreshing, setDomainRefreshing] = useState(false)
  const [domainAutoRefresh, setDomainAutoRefresh] = useState(true)
  const [domainLastCheckedAt, setDomainLastCheckedAt] = useState('')
  const [pageStates, setPageStates] = useState({})
  const [pageStatesRefreshing, setPageStatesRefreshing] = useState(false)
  const pollTimer = useRef(null)
  const domainInputTimer = useRef(null)
  const listPollTimer = useRef(null)

  const selected = useMemo(() => (pages || []).find((p) => p.id === selectedId) || null, [pages, selectedId])

  const refreshPageStates = async (list = pages, { silent = false } = {}) => {
    const source = list || []
    if (!source.length) { setPageStates({}); return }
    if (!silent) setPageStatesRefreshing(true)
    try {
      const pairs = await Promise.all(source.map(async (page) => {
        try {
          const state = await api.landingPages.domainStatus(page.id, page.domain)
          return [page.id, state]
        } catch (e) {
          return [page.id, { error: e.message, page: { published: page.isPublished, version: page.version } }]
        }
      }))
      setPageStates(Object.fromEntries(pairs))
    } finally {
      if (!silent) setPageStatesRefreshing(false)
    }
  }

  const load = async (keepId = selectedId) => {
    try {
      setError('')
      const list = await api.landingPages.list()
      setPages(list)
      refreshPageStates(list, { silent: true })
      const id = list.some((p) => p.id === keepId) ? keepId : list[0]?.id || null
      setSelectedId(id)
      const item = list.find((p) => p.id === id)
      if (item) setForm(normalized(item))
    } catch (e) { setError(e.message) }
  }

  useEffect(() => { load(null); api.landingPages.cloudflareConfig().then(setCfConfig).catch(() => setCfConfig({ configured: false })) }, [])
  useEffect(() => {
    if (!selected) { setStats(null); setDomainState(null); setDomainLastCheckedAt(''); return }
    setForm(normalized(selected))
    api.landingPages.stats(selected.id, 30).then(setStats).catch(() => setStats(null))
    api.landingPages.domainStatus(selected.id, selected.domain)
      .then((state) => {
        setDomainState(state)
        setDomainLastCheckedAt(new Date().toISOString())
        setPageStates((prev) => ({ ...prev, [selected.id]: state }))
      })
      .catch((e) => setDomainState({ error: e.message }))
  }, [selectedId, selected?.version, selected?.domain])

  const setContent = (key, value) => setForm((f) => ({ ...f, content: { ...f.content, [key]: value } }))
  const setSeo = (key, value) => setForm((f) => ({ ...f, seo: { ...f.seo, [key]: value } }))
  const setGoogle = (key, value) => setForm((f) => ({ ...f, google: { ...f.google, [key]: value } }))

  const save = async () => {
    if (!selected) return
    setBusy(true); setError('')
    try {
      await api.landingPages.update(selected.id, form)
      notify('Чернетку збережено')
      await load(selected.id)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const publish = async () => {
    if (!selected) return
    setBusy(true); setError('')
    try {
      await api.landingPages.update(selected.id, form)
      const next = await api.landingPages.publish(selected.id)
      notify(`Опубліковано версію ${next.version}`)
      await load(selected.id)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const unpublish = async () => {
    if (!selected || !window.confirm(`Зняти «${selected.name}» з публікації?`)) return
    setBusy(true)
    try { await api.landingPages.unpublish(selected.id); notify('Публікацію вимкнено'); await load(selected.id) }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!selected || !window.confirm(`Видалити промо-сторінку «${selected.name}»? Статистика також буде видалена.`)) return
    setBusy(true)
    try { await api.landingPages.remove(selected.id); notify('Сторінку видалено'); await load(null) }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const preview = async () => {
    if (!selected) return
    try {
      await api.landingPages.update(selected.id, form)
      const html = await api.landingPages.preview(selected.id)
      // Preview lives in a blob: document, so relative /media/... URLs would
      // otherwise resolve against blob:. Anchor them to the dashboard origin.
      const previewHtml = html.replace('</head>', `<base href="${window.location.origin}/"></head>`)
      const blob = new Blob([previewHtml], { type: 'text/html;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const win = window.open(url, '_blank', 'noopener,noreferrer')
      setTimeout(() => URL.revokeObjectURL(url), 60000)
      if (!win) notify('Браузер заблокував нову вкладку', 'bad')
    } catch (e) { setError(e.message) }
  }

  const create = async () => {
    setBusy(true); setError('')
    try {
      const item = await api.landingPages.create(form)
      setCreating(false); notify('Промо-сторінку створено'); await load(item.id)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const generateSeo = async () => {
    if (!selected || seoBusy) return
    setSeoBusy(true); setError('')
    try {
      const seo = await api.landingPages.generateSeo(selected.id, { name: form.name, domain: form.domain, content: form.content })
      setForm((f) => ({ ...f, seo }))
      notify('SEO згенеровано з поточного контенту. Перевірте й збережіть зміни.')
    } catch (e) { setError(e.message) } finally { setSeoBusy(false) }
  }

  const refreshDomain = async ({ silent = false } = {}) => {
    if (!selected) return null
    if (!silent) setDomainRefreshing(true)
    try {
      const state = await api.landingPages.domainStatus(selected.id, form.domain || selected.domain)
      setDomainState(state)
      setPageStates((prev) => selected ? ({ ...prev, [selected.id]: state }) : prev)
      setDomainLastCheckedAt(new Date().toISOString())
      return state
    } catch (e) {
      setDomainState({ error: e.message })
      return null
    } finally {
      if (!silent) setDomainRefreshing(false)
    }
  }

  const connectDomain = async () => {
    if (!selected || domainBusy) return
    setDomainBusy(true); setError('')
    try {
      await api.landingPages.update(selected.id, form)
      const state = await api.landingPages.domainConnect(selected.id)
      setDomainState(state)
      notify(state?.active ? 'Домен підключено, HTTPS активний' : 'Підключення запущено, виконуємо додаткові перевірки')
      await refreshDomain({ silent: true })
    } catch (e) { setError(e.message); await refreshDomain() } finally { setDomainBusy(false) }
  }

  const saveCloudflare = async () => {
    if (!cfToken.trim() || cfBusy) return
    setCfBusy(true); setError('')
    try {
      const result = await api.landingPages.cloudflareSave(cfToken.trim())
      setCfConfig(result); setCfToken('')
      notify('Cloudflare API підключено')
      await refreshDomain({ silent: true })
    } catch (e) { setError(e.message) } finally { setCfBusy(false) }
  }

  const syncCloudflareDns = async () => {
    if (cfBusy || !form.domain.trim()) return
    setCfBusy(true); setError('')
    try {
      await api.landingPages.cloudflareSync(form.domain.trim())
      notify('Cloudflare DNS синхронізовано: A → VPS, Proxy увімкнено')
      await refreshDomain({ silent: true })
    } catch (e) { setError(e.message) } finally { setCfBusy(false) }
  }

  const enableCloudflareStrict = async () => {
    if (cfBusy || !form.domain.trim()) return
    setCfBusy(true); setError('')
    try {
      await api.landingPages.cloudflareStrict(form.domain.trim())
      notify('Cloudflare SSL mode: Full (strict)')
      await refreshDomain({ silent: true })
    } catch (e) { setError(e.message) } finally { setCfBusy(false) }
  }

  const removeCloudflare = async () => {
    if (cfBusy || !window.confirm('Відключити Cloudflare API? DNS-записи у Cloudflare не змінюватимуться.')) return
    setCfBusy(true); setError('')
    try { const result = await api.landingPages.cloudflareRemove(); setCfConfig(result); notify('Cloudflare API відключено'); await refreshDomain({ silent: true }) }
    catch (e) { setError(e.message) } finally { setCfBusy(false) }
  }

  const disconnectDomain = async () => {
    if (!selected || domainBusy || !window.confirm(`Відключити ${selected.domain}? Публічна сторінка стане недоступною.`)) return
    setDomainBusy(true); setError('')
    try {
      const state = await api.landingPages.domainDisconnect(selected.id)
      setDomainState(state)
      notify('Домен відключено')
      await refreshDomain({ silent: true })
    } catch (e) { setError(e.message) } finally { setDomainBusy(false) }
  }

  useEffect(() => {
    if (tab !== 'deploy' || !selected) return undefined
    if (domainInputTimer.current) clearTimeout(domainInputTimer.current)
    domainInputTimer.current = setTimeout(() => {
      if (form.domain?.trim()) refreshDomain({ silent: true })
    }, 700)
    return () => {
      if (domainInputTimer.current) clearTimeout(domainInputTimer.current)
    }
  }, [form.domain, selected?.id, tab])

  useEffect(() => {
    if (tab !== 'deploy' || !selected || !domainAutoRefresh) {
      if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null }
      return undefined
    }
    const shouldPollFast = domainBusy || domainRefreshing || !domainState?.active
    const intervalMs = shouldPollFast ? 5000 : 15000
    pollTimer.current = setInterval(() => {
      refreshDomain({ silent: true })
    }, intervalMs)
    return () => {
      if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null }
    }
  }, [tab, selected?.id, domainAutoRefresh, domainBusy, domainRefreshing, domainState?.active])

  useEffect(() => {
    if (!pages?.length) return undefined
    refreshPageStates(pages, { silent: true })
    listPollTimer.current = setInterval(() => { refreshPageStates(pages, { silent: true }) }, 15000)
    return () => {
      if (listPollTimer.current) { clearInterval(listPollTimer.current); listPollTimer.current = null }
    }
  }, [pages?.length, pages?.map((p) => `${p.id}:${p.version}:${p.isPublished}`).join('|')])

  const checkSummary = domainCheckSummary(domainState)
  const checkingText = prettyCheckState(domainRefreshing || domainBusy, domainState, domainAutoRefresh)
  const readiness = deployReadiness(domainState)
  const currentRuntime = promoRuntimeInfo(selected, pageStates[selected?.id])

  if (!pages) return <Loading rows={5} />

  return <div>
    <div className="page-head">
      <div><h1>Промо-сторінки</h1><p>Тут менеджер працює лише з тим, що справді потрібно: тексти, зображення, промокод, адреса сайту та SEO. Усі технічні деталі панель бере на себе.</p></div>
      <button className="btn" onClick={() => { setForm(newForm()); setCreating(true) }}>Створити сторінку</button>
    </div>
    <ErrorBar error={error} />

    {pages.length === 0 ? <Empty title="Ще немає промо-сторінок">Створіть першу сторінку та прив'яжіть до неї домен.</Empty> : <div className="promo-builder-layout">
      <aside className="card promo-page-list">
        {(pages || []).map((p) => {
          const runtime = promoRuntimeInfo(p, pageStates[p.id])
          return <button key={p.id} className={`promo-page-item ${p.id === selectedId ? 'active' : ''}`} onClick={() => setSelectedId(p.id)}>
            <div className="promo-page-item-top">
              <strong>{p.name}</strong>
              <span className={`promo-page-badge ${runtime.tone}`}>{runtime.badge}</span>
            </div>
            <span>{p.domain}</span>
            <small>{p.isPublished ? `Опубліковано · версія ${p.version}` : 'Ще не опубліковано'}</small>
            <div className="promo-page-runtime">{runtime.text}</div>
          </button>
        })}
        {pageStatesRefreshing && <div className="promo-page-status-note">Оновлюємо стан сторінок…</div>}
      </aside>

      {selected && <section className="stack" style={{ gap: 14 }}>
        <div className="card promo-builder-toolbar">
          <div>
            <strong>{selected.name}</strong>
            <div className="faint">{selected.publicUrl} · {selected.isPublished ? `опубліковано, версія ${selected.version}` : 'ще не опубліковано'}</div>
            <div className={`promo-toolbar-runtime ${currentRuntime.tone}`}>{currentRuntime.badge}: {currentRuntime.text}</div>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <button className="btn ghost" onClick={preview} disabled={busy}>Перегляд</button>
            <button className="btn ghost" onClick={save} disabled={busy}>Зберегти</button>
            <button className="btn" onClick={publish} disabled={busy}>{busy ? 'Публікуємо…' : 'Опублікувати'}</button>
            {selected.isPublished && <a className="btn ghost" href={`https://${form.domain || selected.domain}/`} target="_blank" rel="noreferrer">Відкрити сайт</a>}
            {selected.isPublished && <button className="btn ghost" onClick={unpublish} disabled={busy}>Зняти з публікації</button>}
            <button className="btn danger" onClick={remove} disabled={busy}>Видалити</button>
          </div>
        </div>

        <div className="promo-tabs">
          <button className={tab === 'content' ? 'active' : ''} onClick={() => setTab('content')}>Сторінка</button>
          <button className={tab === 'seo' ? 'active' : ''} onClick={() => setTab('seo')}>SEO</button>
          <button className={tab === 'google' ? 'active' : ''} onClick={() => setTab('google')}>Google</button>
          <button className={tab === 'stats' ? 'active' : ''} onClick={() => setTab('stats')}>Статистика</button>
          <button className={tab === 'deploy' ? 'active' : ''} onClick={() => setTab('deploy')}>Домен і деплой</button>
        </div>

        {tab === 'content' && <div className="card">
          <div className="grid k2">
            <Field label="Внутрішня назва"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Домен"><input className="input" value={form.domain} placeholder="promo.example.com" onChange={(e) => setForm({ ...form, domain: e.target.value })} /></Field>
          </div>
          <div className="grid k2" style={{ marginTop: 16 }}>
            <ImageField label="Фон сторінки" value={form.content.background_image} onChange={(v) => setContent('background_image', v)} hint="Для промо дозволяються тільки файли з локального /media/." />
            <ImageField label="Логотип" value={form.content.logo_image} onChange={(v) => setContent('logo_image', v)} hint="Завантажте у локальне сховище." />
          </div>
          <div className="grid k2">
            <Field label="Надзаголовок"><input className="input" value={form.content.eyebrow} onChange={(e) => setContent('eyebrow', e.target.value)} /></Field>
            <Field label="Заголовок"><input className="input" value={form.content.title} onChange={(e) => setContent('title', e.target.value)} /></Field>
            <Field label="Підпис промокоду"><input className="input" value={form.content.promo_label} onChange={(e) => setContent('promo_label', e.target.value)} /></Field>
            <Field label="Промокод"><input className="input mono" value={form.content.promo_code} onChange={(e) => setContent('promo_code', e.target.value)} /></Field>
            <Field label="Текст пропозиції"><textarea className="input" rows="4" value={form.content.description} onChange={(e) => setContent('description', e.target.value)} /></Field>
            <Field label="Текст терміну дії"><textarea className="input" rows="4" value={form.content.validity_text} onChange={(e) => setContent('validity_text', e.target.value)} /></Field>
            <Field label="Текст кнопки"><input className="input" value={form.content.button_text} onChange={(e) => setContent('button_text', e.target.value)} /></Field>
            <Field label="Посилання кнопки"><input className="input" value={form.content.button_url} placeholder="https://t.me/..." onChange={(e) => setContent('button_url', e.target.value)} /></Field>
          </div>
          <Field label="Нижній текст"><textarea className="input" rows="3" value={form.content.footer_text} onChange={(e) => setContent('footer_text', e.target.value)} /></Field>
        </div>}

        {tab === 'seo' && <div className="card">
          <div className="promo-seo-head">
            <div>
              <h2 style={{ marginTop: 0, marginBottom: 6 }}>SEO</h2>
              <p className="faint" style={{ margin: 0 }}>Semantic HTML, canonical, Open Graph, Twitter Card і JSON-LD формуються шаблоном автоматично. Дані нижче можна редагувати вручну.</p>
            </div>
            <button className="btn ghost" onClick={generateSeo} disabled={seoBusy}>{seoBusy ? 'Генеруємо…' : 'Згенерувати SEO'}</button>
          </div>
          <div className="promo-seo-generator-note">
            <strong>Контекстний генератор</strong>
            <span>Під час створення сторінки SEO заповнюється автоматично з назви, домену, заголовка, опису, промокоду, терміну дії, CTA та вибраних зображень. Повторна генерація створює іншу коректну варіацію, але не вигадує факти, яких немає у промо.</span>
          </div>
          <div className="grid k2">
            <Field label={<SeoLabel field="title" />} hint={`${form.seo.title.length}/70`}><input className="input" value={form.seo.title} onChange={(e) => setSeo('title', e.target.value)} /></Field>
            <Field label={<SeoLabel field="canonical_url" />}><input className="input" value={form.seo.canonical_url} placeholder={`https://${form.domain || 'domain.example'}/`} onChange={(e) => setSeo('canonical_url', e.target.value)} /></Field>
            <Field label={<SeoLabel field="description" />} hint={`${form.seo.description.length}/180`}><textarea className="input" rows="4" value={form.seo.description} onChange={(e) => setSeo('description', e.target.value)} /></Field>
            <Field label={<SeoLabel field="keywords" />}><textarea className="input" rows="4" value={form.seo.keywords} onChange={(e) => setSeo('keywords', e.target.value)} /></Field>
            <Field label={<SeoLabel field="robots" />}><input className="input" value={form.seo.robots} onChange={(e) => setSeo('robots', e.target.value)} /></Field>
            <Field label={<SeoLabel field="og_locale" />}><input className="input" value={form.seo.og_locale} onChange={(e) => setSeo('og_locale', e.target.value)} /></Field>
            <Field label={<SeoLabel field="og_title" />} hint={`${form.seo.og_title.length}/100`}><input className="input" value={form.seo.og_title} onChange={(e) => setSeo('og_title', e.target.value)} /></Field>
            <Field label={<SeoLabel field="og_description" />} hint={`${form.seo.og_description.length}/200`}><textarea className="input" rows="3" value={form.seo.og_description} onChange={(e) => setSeo('og_description', e.target.value)} /></Field>
            <Field label={<SeoLabel field="site_name" />}><input className="input" value={form.seo.site_name} onChange={(e) => setSeo('site_name', e.target.value)} /></Field>
            <Field label={<SeoLabel field="schema_name" />}><input className="input" value={form.seo.schema_name} onChange={(e) => setSeo('schema_name', e.target.value)} /></Field>
          </div>
          <div className="seo-image-field"><div className="seo-image-title"><SeoLabel field="og_image" /></div><ImageField label="Зображення" value={form.seo.og_image} onChange={(v) => setSeo('og_image', v)} hint="Локальний файл із /media/. Якщо порожньо — renderer використає фон або логотип." /></div>
          <Field label={<SeoLabel field="schema_description" />} hint={`${form.seo.schema_description.length}/240`}><textarea className="input" rows="3" value={form.seo.schema_description} onChange={(e) => setSeo('schema_description', e.target.value)} /></Field>
        </div>}

        {tab === 'google' && <div className="stack" style={{ gap: 14 }}>
          <div className="card promo-google-card">
            <div className="promo-google-head">
              <div>
                <h2 style={{ marginTop: 0, marginBottom: 6 }}>Google</h2>
                <p className="faint" style={{ margin: 0 }}>Аналітика, рекламні конверсії, Tag Manager і підтвердження Search Console для цієї промо-сторінки.</p>
              </div>
              <label className="promo-google-switch"><input type="checkbox" checked={!!form.google.enabled} onChange={(e) => setGoogle('enabled', e.target.checked)} /><span>Відстеження увімкнено</span></label>
            </div>

            <div className="promo-google-note"><strong>Без дублювання тегів</strong><span>Виберіть один спосіб підключення: Google tag або Google Tag Manager. Панель не вставляє довільний JavaScript і приймає лише валідні Google ID.</span></div>

            <div className="grid k2">
              <Field label="Спосіб підключення" hint={GOOGLE_HELP.mode}>
                <select className="input" value={form.google.mode} onChange={(e) => setGoogle('mode', e.target.value)}>
                  <option value="google_tag">Google tag / GA4 / Google Ads</option>
                  <option value="gtm">Google Tag Manager</option>
                </select>
              </Field>
              <Field label="Згода на аналітику" hint={GOOGLE_HELP.consent_mode}>
                <select className="input" value={form.google.consent_mode} onChange={(e) => setGoogle('consent_mode', e.target.value)}>
                  <option value="banner">Вбудований банер — рекомендовано</option>
                  <option value="granted">Дозволено одразу</option>
                  <option value="disabled">Consent Mode вимкнено</option>
                </select>
              </Field>
            </div>

            {form.google.mode === 'google_tag' ? <div className="grid k2">
              <Field label="Google tag ID" hint={GOOGLE_HELP.google_tag_id}><input className="input mono" value={form.google.google_tag_id} placeholder="G-XXXXXXXXXX" onChange={(e) => setGoogle('google_tag_id', e.target.value.trim())} /></Field>
              <div className="promo-google-status-box"><span>Що буде передаватися</span><strong>Перегляд сторінки + подія promo_cta_click</strong><small>Якщо нижче задано Google Ads ID і Label — клік CTA також піде як conversion.</small></div>
            </div> : <div className="grid k2">
              <Field label="GTM Container ID" hint={GOOGLE_HELP.gtm_container_id}><input className="input mono" value={form.google.gtm_container_id} placeholder="GTM-XXXXXXX" onChange={(e) => setGoogle('gtm_container_id', e.target.value.trim())} /></Field>
              <div className="promo-google-status-box"><span>Подія для GTM</span><strong>promo_cta_click</strong><small>Створіть Trigger у GTM на Custom Event з цією назвою та прив'яжіть потрібні GA4/Ads теги.</small></div>
            </div>}
          </div>

          <div className="card promo-google-card">
            <h3 style={{ marginTop: 0 }}>Google Ads</h3>
            <p className="faint">Необов'язково. Для прямої конверсії використовуйте разом із режимом Google tag.</p>
            <div className="grid k2">
              <Field label="Conversion ID" hint={GOOGLE_HELP.ads_conversion_id}><input className="input mono" value={form.google.ads_conversion_id} placeholder="AW-123456789" onChange={(e) => setGoogle('ads_conversion_id', e.target.value.trim())} /></Field>
              <Field label="Conversion Label" hint={GOOGLE_HELP.ads_conversion_label}><input className="input mono" value={form.google.ads_conversion_label} placeholder="AbCdEfGhIjKlMn" onChange={(e) => setGoogle('ads_conversion_label', e.target.value.trim())} /></Field>
            </div>
            {form.google.mode === 'gtm' && (form.google.ads_conversion_id || form.google.ads_conversion_label) && <div className="promo-google-warning">У режимі GTM ці два поля не запускають conversion напряму. Використовуйте подію <code>promo_cta_click</code> у контейнері GTM.</div>}
          </div>

          <div className="card promo-google-card">
            <h3 style={{ marginTop: 0 }}>Google Search Console</h3>
            <Field label="Verification token" hint={GOOGLE_HELP.search_console_verification}><input className="input mono" value={form.google.search_console_verification} placeholder="значення з content=..." onChange={(e) => setGoogle('search_console_verification', e.target.value.trim())} /></Field>
            <div className="promo-google-note"><strong>Як вставляється</strong><span>Панель сама створить meta-тег <code>google-site-verification</code> у &lt;head&gt;. Повний HTML-код вставляти не потрібно.</span></div>
          </div>

          <div className="card promo-google-card">
            <h3 style={{ marginTop: 0 }}>Стан інтеграції</h3>
            <div className="promo-google-summary">
              <div><span>Аналітика</span><strong>{form.google.enabled ? (form.google.mode === 'gtm' ? (form.google.gtm_container_id ? 'Налаштовано' : 'Потрібен GTM ID') : (form.google.google_tag_id ? 'Налаштовано' : 'Потрібен Google tag ID')) : 'Вимкнена'}</strong></div>
              <div><span>Ads conversion</span><strong>{form.google.ads_conversion_id && form.google.ads_conversion_label ? (form.google.mode === 'google_tag' ? 'Готова' : 'Через GTM') : 'Не задана'}</strong></div>
              <div><span>Search Console</span><strong>{form.google.search_console_verification ? 'Verification додано' : 'Не задано'}</strong></div>
              <div><span>Consent</span><strong>{form.google.consent_mode === 'banner' ? 'Банер' : form.google.consent_mode === 'granted' ? 'Дозволено одразу' : 'Вимкнено'}</strong></div>
            </div>
          </div>
        </div>}

        {tab === 'stats' && <div className="stack" style={{ gap: 14 }}>
          <div className="grid k3">
            <Metric label="Перегляди · 30 днів" value={stats?.views ?? '—'} />
            <Metric label="Кліки CTA · 30 днів" value={stats?.clicks ?? '—'} />
            <Metric label="CTR" value={stats ? `${stats.ctr}%` : '—'} sub="кліки / перегляди" />
          </div>
          <div className="card table-wrap"><table><thead><tr><th>День</th><th>Перегляди</th><th>Кліки</th><th>CTR</th></tr></thead><tbody>
            {(stats?.items || []).map((i) => <tr key={i.day}><td>{i.day}</td><td>{i.views}</td><td>{i.clicks}</td><td>{i.views ? `${(i.clicks / i.views * 100).toFixed(2)}%` : '0%'}</td></tr>)}
            {!stats?.items?.length && <tr><td colSpan="4" className="faint">Даних ще немає.</td></tr>}
          </tbody></table></div>
        </div>}

        {tab === 'deploy' && <div className="card">
          <h2 style={{ marginTop: 0 }}>Домен і запуск сайту</h2>
          <p><strong>Усе керується прямо з панелі.</strong> Тут ви бачите, чи готовий домен, чи працює захищене з'єднання і чи сайт реально відкривається для людей.</p>
          <div className="promo-check-banner">
            <div className={`promo-check-dot ${(domainRefreshing || domainBusy) ? 'is-checking' : checkSummary.overall === 'ready' ? 'is-ok' : checkSummary.overall === 'progress' ? 'is-progress' : 'is-waiting'}`} aria-hidden="true"></div>
            <div className="promo-check-banner-copy">
              <strong>{checkingText}</strong>
              <span>{domainLastCheckedAt ? `Остання перевірка: ${new Date(domainLastCheckedAt).toLocaleString('uk-UA')}` : 'Щойно відкрили блок деплою — перша перевірка виконається автоматично.'}</span>
            </div>
            <label className="promo-auto-refresh-toggle">
              <input type="checkbox" checked={domainAutoRefresh} onChange={(e) => setDomainAutoRefresh(e.target.checked)} />
              <span>Автоперевірка без перезавантаження</span>
            </label>
          </div>

          <div className="promo-check-steps">
            {checkSummary.steps.map((step, index) => <div key={step.key} className={`promo-check-step ${step.status}${(domainRefreshing || domainBusy) ? ' live' : ''}`}>
              <div className="promo-check-step-top">
                <span className="promo-check-step-index">{index + 1}</span>
                <strong>{step.title}</strong>
              </div>
              <div className="promo-check-step-text">{step.text}</div>
            </div>)}
          </div>

          <div className="promo-cloudflare-card">
            <div className="promo-cloudflare-head">
              <div>
                <h3>Cloudflare API</h3>
                <p>Для proxied-доменів перевіряємо прихований origin через Cloudflare API, а не порівнюємо публічні Cloudflare IP з IP VPS.</p>
              </div>
              <span className={`promo-dns-badge ${domainState?.cloudflare?.readyForProxyDeploy ? 'ok' : domainState?.cloudflare?.configured ? 'warn' : ''}`}>
                {domainState?.cloudflare?.readyForProxyDeploy ? 'Proxy перевірено' : domainState?.cloudflare?.configured ? 'Підключено' : 'Не підключено'}
              </span>
            </div>

            {canConfigureCloudflare && <div className="promo-cloudflare-connect">
              <input className="input" type="password" autoComplete="new-password" value={cfToken} onChange={(e) => setCfToken(e.target.value)} placeholder={cfConfig?.configured ? 'Введіть новий API Token, щоб замінити поточний' : 'Cloudflare API Token'} />
              <button className="btn ghost" onClick={saveCloudflare} disabled={cfBusy || !cfToken.trim()}>{cfBusy ? 'Перевіряємо…' : cfConfig?.configured ? 'Замінити токен' : 'Підключити Cloudflare'}</button>
              {cfConfig?.configured && <button className="btn danger" onClick={removeCloudflare} disabled={cfBusy}>Відключити API</button>}
            </div>}
            <div className="promo-cloudflare-help">
              <strong>Мінімальні права токена:</strong> Zone Read, DNS Read/Write, Zone Settings Read. Для кнопки Full (strict) потрібен Zone Settings Edit. Сам токен зберігається зашифровано і назад у браузер не повертається.
            </div>
            {canConfigureCloudflare && cfConfig?.configured && <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
              <button className="btn ghost" onClick={syncCloudflareDns} disabled={cfBusy || !form.domain.trim()}>{cfBusy ? 'Виконуємо…' : 'Синхронізувати DNS + Proxy'}</button>
              {!domainState?.cloudflare?.strict && <button className="btn ghost" onClick={enableCloudflareStrict} disabled={cfBusy || !form.domain.trim()}>Увімкнути Full (strict)</button>}
            </div>}

            {domainState?.cloudflare?.detected && <div className="promo-cloudflare-grid">
              <div><span>Zone</span><strong>{domainState.cloudflare.zone?.name || '—'}</strong></div>
              <div><span>Proxy</span><strong>{domainState.cloudflare.proxied ? '🟠 Proxied' : 'DNS only'}</strong></div>
              <div><span>Origin VPS</span><strong>{domainState.cloudflare.originIpv4 || '—'}</strong></div>
              <div><span>Origin у Cloudflare</span><strong>{domainState.cloudflare.originMatches ? 'Збігається' : 'Не збігається'}</strong></div>
              <div><span>SSL mode</span><strong>{domainState.cloudflare.sslMode || 'Немає доступу'}</strong></div>
              <div><span>Full (strict)</span><strong>{domainState.cloudflare.strict ? 'Так' : 'Ні'}</strong></div>
            </div>}

            {!!domainState?.cloudflare?.records?.length && <div className="promo-cloudflare-records">
              {domainState.cloudflare.records.map((r) => <div key={r.id || `${r.type}-${r.content}`} className="promo-cloudflare-record">
                <strong>{r.type}</strong><code>{r.name}</code><span>→</span><code>{r.content}</code><span>{r.proxied ? '🟠 Proxied' : 'DNS only'}</span>
              </div>)}
            </div>}
            {domainState?.cloudflare?.error && <div className="error-bar">Cloudflare: {domainState.cloudflare.error}</div>}
          </div>

          <div className="grid k2">
            <Field label="Домен" hint={domainState?.routePresent ? 'Щоб змінити домен, спочатку відключіть поточний route.' : 'A/AAAA запис має вже вести на цей сервер.'}>
              <input className="input" value={form.domain} disabled={!!domainState?.routePresent} onChange={(e) => setForm({ ...form, domain: e.target.value })} />
            </Field>
            <Field label="Production URL"><input className="input" readOnly value={`https://${form.domain || 'domain.example'}/`} /></Field>
          </div>

          <div className="promo-dns-setup">
            <div className="promo-dns-setup-head">
              <div>
                <h3>Що потрібно налаштувати в домені</h3>
                <p>Скопіюйте записи нижче у вашу DNS-панель. Коли зміни поширяться, панель сама це побачить і дозволить перейти до запуску сайту.</p>
              </div>
              <span className={`promo-dns-badge ${(domainRefreshing || domainBusy) ? 'checking' : domainState?.dns?.pointsHere === true ? 'ok' : 'warn'}`}> 
                {domainState?.dns?.pointsHere === true ? 'DNS веде на цей VPS' : domainState?.dns?.propagating ? 'DNS ще поширюється' : domainState?.dns?.ok ? 'DNS веде на іншу адресу' : 'Очікуємо DNS'}
              </span>
            </div>

            {domainState?.dnsRequirements?.configured ? <div className="promo-dns-records">
              {(domainState.dnsRequirements.records || []).map((record) => <div className="promo-dns-record" key={`${record.type}-${record.value}`}>
                <div><span className="label">Тип</span><strong>{record.type}</strong></div>
                <div><span className="label">Name / Host</span><CopyValue value={record.host} /></div>
                <div><span className="label">Значення / Points to</span><CopyValue value={record.value} /></div>
                <div><span className="label">Обов’язковість</span><strong>{record.required ? 'Обов’язковий' : 'Необов’язковий'}</strong></div>
              </div>)}
            </div> : <div className="error-bar">Не вдалося автоматично визначити публічну IPv4-адресу VPS. Перевірте вихід promo-controller в інтернет або задайте PROMO_PUBLIC_IPV4 як аварійний override.</div>}

            {domainState?.dnsRequirements?.configured && <div className="promo-dns-current" style={{ marginTop: 10 }}>
              <span><strong>IP VPS:</strong> {domainState.dnsRequirements.ipv4 || '—'}</span>
              <span><strong>Джерело:</strong> {domainState.dnsRequirements.autoDetected ? 'визначено автоматично' : 'ручний override'}</span>
              {domainState.dnsRequirements.detectedAt && <span><strong>Перевірено:</strong> {new Date(domainState.dnsRequirements.detectedAt).toLocaleString('uk-UA')}</span>}
              <span><strong>IPv6:</strong> {domainState.dnsRequirements.ipv6 || 'не виявлено / не використовується'}</span>
            </div>}

            <div className="promo-dns-note">
              <strong>Що саме вносити у провайдера домену</strong>
              <span>{domainState?.dnsRequirements?.note || 'Для IPv4 потрібен A-запис на публічну IPv4-адресу VPS. AAAA додавайте тільки якщо IPv6 реально налаштований.'}</span>
              <span><strong>TTL:</strong> можна залишити Auto/Default. Для первинного підключення зручно 300–600 секунд, якщо провайдер дозволяє.</span>
              <span><strong>AAAA:</strong> не створюйте його лише «для галочки». Неправильний IPv6 може зробити сайт недоступним для частини клієнтів.</span>
            </div>

            <div className={`promo-ns-card ${domainState?.nameservers?.isNicUa ? 'nic' : domainState?.nameservers?.ok ? 'external' : 'warn'}`}>
              <div className="promo-ns-head">
                <div>
                  <span className="label">NS / DNS-провайдер</span>
                  <strong>{domainState?.nameservers?.provider || 'Перевіряємо…'}</strong>
                </div>
                <span className="promo-ns-action">{domainState?.nameservers?.isNicUa ? 'NS НЕ ЗМІНЮВАТИ' : domainState?.nameservers?.ok ? 'Редагуйте DNS у поточного провайдера' : 'Потрібна перевірка делегування'}</span>
              </div>
              {!!domainState?.nameservers?.nameservers?.length && <div className="promo-ns-list">
                {domainState.nameservers.nameservers.map((ns) => <CopyValue key={ns} value={ns} />)}
              </div>}
              <p>{domainState?.nameservers?.action || 'Авторитетні NS визначаються автоматично. Панель не змінює їх сама.'}</p>
              {domainState?.nameservers?.isNicUa && <div className="promo-nic-steps">
                <strong>Для NIC.UA</strong>
                <span>1. Відкрийте NIC.UA → «Сервери імен (NS)» → потрібний домен → DNS-записи.</span>
                <span>2. Для кореневого домену змініть <code>A</code> запис <code>@</code> на IP VPS, показаний вище. Для піддомену використайте його коротке ім’я.</span>
                <span>3. Поточні NIC.UA NS залиште без змін. Типові NS NIC.UA: <code>ns10.uadns.com</code>, <code>ns11.uadns.com</code>, <code>ns12.uadns.com</code>.</span>
              </div>}
              {!domainState?.nameservers?.isNicUa && domainState?.nameservers?.ok && <div className="promo-nic-steps">
                <strong>Важливо</strong>
                <span>Домен може бути зареєстрований у NIC.UA, але DNS зараз обслуговується іншим провайдером. У такому разі A/AAAA треба змінювати саме там, куди вказують поточні NS.</span>
              </div>}
            </div>

            <div className="promo-dns-current">
              <span><strong>Зараз бачимо:</strong> {(domainState?.dns?.addresses || []).join(', ') || 'ще немає адрес'}</span>
              {!!domainState?.dns?.expected?.length && <span><strong>Очікуємо:</strong> {domainState.dns.expected.join(', ')}</span>}
              {!!domainState?.dns?.wrongAddresses?.length && <span className="promo-dns-wrong"><strong>Старі/зайві:</strong> {domainState.dns.wrongAddresses.join(', ')}</span>}
              {!!domainState?.dns?.successfulResolvers && <span><strong>Публічні резолвери:</strong> {domainState.dns.successfulResolvers}</span>}
            </div>
          </div>

          <div className="grid k4" style={{ marginTop: 14 }}>
            <Metric label="Публічна адреса" value={domainRefreshing ? 'Перевіряємо…' : domainState?.routePresent ? 'Активна' : 'Ще ні'} />
            <Metric label="Домен" value={domainRefreshing ? 'Перевіряємо…' : domainState?.dns?.pointsHere === true ? 'Готовий' : domainState?.dns?.ok ? 'Інша адреса' : 'Не готовий'} sub={(domainState?.dns?.addresses || []).join(', ') || domainState?.dns?.error || ''} />
            <Metric label="HTTPS" value={domainRefreshing ? 'Перевіряємо…' : domainState?.tls?.present ? 'Активний' : 'Ще ні'} sub={domainState?.tls?.expiresAt ? `до ${new Date(domainState.tls.expiresAt).toLocaleDateString('uk-UA')}` : ''} />
            <Metric label="Стан сайту" value={domainRefreshing ? 'Перевіряємо…' : domainState?.live?.label || 'Очікуємо'} sub={domainState?.live?.message || ''} />
          </div>

          {domainState?.error && <div className="error-bar" style={{ marginTop: 14 }}>{domainState.error}</div>}

          <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 16 }}>
            {!domainState?.routePresent && <button className="btn" onClick={connectDomain} disabled={domainBusy || !form.domain.trim() || domainState?.dns?.pointsHere === false || !domainState?.dnsRequirements?.configured}>
              {domainBusy ? 'Запускаємо…' : 'Запустити сайт'}
            </button>}
            {domainState?.routePresent && !domainState?.active && <button className="btn" onClick={connectDomain} disabled={domainBusy}>
              {domainBusy ? 'Перевіряємо HTTPS…' : 'Повторити перевірку HTTPS'}
            </button>}
            {domainState?.routePresent && <button className="btn danger" onClick={disconnectDomain} disabled={domainBusy}>
              {domainBusy ? 'Відключаємо…' : 'Вимкнути сайт'}
            </button>}
            <button className={`btn ghost ${domainRefreshing ? 'is-loading' : ''}`} onClick={() => refreshDomain()} disabled={domainBusy || domainRefreshing}>{domainRefreshing ? 'Перевіряємо…' : 'Оновити статус'}</button>
            {domainState?.active && <a className="btn ghost" href={`https://${selected.domain}/`} target="_blank" rel="noreferrer">Відкрити сайт</a>}
          </div>

          <div className="card" style={{ marginTop: 14, background: 'var(--panel-2, rgba(0,0,0,.12))' }}>
            <strong>Технічний блок</strong>
            <p className="faint" style={{ marginBottom: 0 }}>Для безпеки доменами керує окремий внутрішній сервіс. Панель не має root або shell-доступу, а технічні деталі винесені в цей блок, щоб не заважати щоденній роботі менеджера.</p>
          </div>
        </div>}
      </section>}
    </div>}

    {creating && <Modal title="Нова промо-сторінка" onClose={() => setCreating(false)} footer={<><button className="btn ghost" onClick={() => setCreating(false)}>Скасувати</button><button className="btn" onClick={create} disabled={busy}>Створити</button></>}>
      <Field label="Назва"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
      <Field label="Домен" hint="Без https:// і без шляху."><input className="input" value={form.domain} placeholder="promo.example.com" onChange={(e) => setForm({ ...form, domain: e.target.value })} /></Field>
    </Modal>}
  </div>
}
