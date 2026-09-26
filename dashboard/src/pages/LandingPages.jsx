import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
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

const newForm = () => ({ name: 'Нова промо-сторінка', domain: '', content: { ...DEFAULT_CONTENT }, seo: { ...DEFAULT_SEO } })

function normalized(page) {
  if (!page) return newForm()
  return {
    name: page.name || '', domain: page.domain || '',
    content: { ...DEFAULT_CONTENT, ...(page.draft?.content || {}) },
    seo: { ...DEFAULT_SEO, ...(page.draft?.seo || {}) },
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
  const [domainRefreshing, setDomainRefreshing] = useState(false)
  const [domainAutoRefresh, setDomainAutoRefresh] = useState(true)
  const [domainLastCheckedAt, setDomainLastCheckedAt] = useState('')
  const pollTimer = useRef(null)
  const domainInputTimer = useRef(null)

  const selected = useMemo(() => (pages || []).find((p) => p.id === selectedId) || null, [pages, selectedId])

  const load = async (keepId = selectedId) => {
    try {
      setError('')
      const list = await api.landingPages.list()
      setPages(list)
      const id = list.some((p) => p.id === keepId) ? keepId : list[0]?.id || null
      setSelectedId(id)
      const item = list.find((p) => p.id === id)
      if (item) setForm(normalized(item))
    } catch (e) { setError(e.message) }
  }

  useEffect(() => { load(null) }, [])
  useEffect(() => {
    if (!selected) { setStats(null); setDomainState(null); setDomainLastCheckedAt(''); return }
    setForm(normalized(selected))
    api.landingPages.stats(selected.id, 30).then(setStats).catch(() => setStats(null))
    api.landingPages.domainStatus(selected.id)
      .then((state) => { setDomainState(state); setDomainLastCheckedAt(new Date().toISOString()) })
      .catch((e) => setDomainState({ error: e.message }))
  }, [selectedId, selected?.version, selected?.domain])

  const setContent = (key, value) => setForm((f) => ({ ...f, content: { ...f.content, [key]: value } }))
  const setSeo = (key, value) => setForm((f) => ({ ...f, seo: { ...f.seo, [key]: value } }))

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
      const state = await api.landingPages.domainStatus(selected.id)
      setDomainState(state)
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

  const checkSummary = domainCheckSummary(domainState)
  const checkingText = prettyCheckState(domainRefreshing || domainBusy, domainState, domainAutoRefresh)

  if (!pages) return <Loading rows={5} />

  return <div>
    <div className="page-head">
      <div><h1>Промо-сторінки</h1><p>Фіксований шаблон без доступу до CSS/JS. Редагуються лише контент, локальні зображення, домен і SEO.</p></div>
      <button className="btn" onClick={() => { setForm(newForm()); setCreating(true) }}>Створити сторінку</button>
    </div>
    <ErrorBar error={error} />

    {pages.length === 0 ? <Empty title="Ще немає промо-сторінок">Створіть першу сторінку та прив'яжіть до неї домен.</Empty> : <div className="promo-builder-layout">
      <aside className="card promo-page-list">
        {(pages || []).map((p) => <button key={p.id} className={`promo-page-item ${p.id === selectedId ? 'active' : ''}`} onClick={() => setSelectedId(p.id)}>
          <strong>{p.name}</strong><span>{p.domain}</span><small>{p.isPublished ? `Опубліковано · v${p.version}` : 'Чернетка'}</small>
        </button>)}
      </aside>

      {selected && <section className="stack" style={{ gap: 14 }}>
        <div className="card promo-builder-toolbar">
          <div><strong>{selected.name}</strong><div className="faint">{selected.publicUrl} · {selected.isPublished ? `production v${selected.version}` : 'не опубліковано'}</div></div>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <button className="btn ghost" onClick={preview} disabled={busy}>Перегляд</button>
            <button className="btn ghost" onClick={save} disabled={busy}>Зберегти</button>
            <button className="btn" onClick={publish} disabled={busy}>{busy ? 'Зберігаю…' : 'Опублікувати'}</button>
            {selected.isPublished && <button className="btn ghost" onClick={unpublish} disabled={busy}>Зняти</button>}
            <button className="btn danger" onClick={remove} disabled={busy}>Видалити</button>
          </div>
        </div>

        <div className="promo-tabs">
          <button className={tab === 'content' ? 'active' : ''} onClick={() => setTab('content')}>Сторінка</button>
          <button className={tab === 'seo' ? 'active' : ''} onClick={() => setTab('seo')}>SEO</button>
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
          <h2 style={{ marginTop: 0 }}>Домен і деплой</h2>
          <p><strong>Менеджеру не потрібна консоль.</strong> Панель сама перевіряє DNS, випускає або оновлює TLS-сертифікат, активує nginx route і показує результат.</p>
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

          <div className="grid k2">
            <Field label="Домен" hint={domainState?.routePresent ? 'Щоб змінити домен, спочатку відключіть поточний route.' : 'A/AAAA запис має вже вести на цей сервер.'}>
              <input className="input" value={form.domain} disabled={!!domainState?.routePresent} onChange={(e) => setForm({ ...form, domain: e.target.value })} />
            </Field>
            <Field label="Production URL"><input className="input" readOnly value={`https://${form.domain || 'domain.example'}/`} /></Field>
          </div>

          <div className="promo-dns-setup">
            <div className="promo-dns-setup-head">
              <div>
                <h3>Налаштування DNS перед деплоєм</h3>
                <p>Спочатку внесіть ці записи у DNS-панелі домену. Після поширення DNS натисніть «Оновити статус», і лише тоді підключайте HTTPS.</p>
              </div>
              <span className={`promo-dns-badge ${(domainRefreshing || domainBusy) ? 'checking' : domainState?.dns?.pointsHere === true ? 'ok' : 'warn'}`}> 
                {domainState?.dns?.pointsHere === true ? 'DNS веде на цей VPS' : domainState?.dns?.ok ? 'DNS веде на іншу адресу' : 'Очікуємо DNS'}
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
              <span><strong>Зараз резолвиться:</strong> {(domainState?.dns?.addresses || []).join(', ') || 'ще немає адрес'}</span>
              {!!domainState?.dns?.expected?.length && <span><strong>Очікуємо:</strong> {domainState.dns.expected.join(', ')}</span>}
            </div>
          </div>

          <div className="grid k3" style={{ marginTop: 14 }}>
            <Metric label="Маршрут" value={domainRefreshing ? 'Перевіряємо…' : domainState?.routePresent ? 'Активний' : 'Не створено'} />
            <Metric label="DNS" value={domainRefreshing ? 'Перевіряємо…' : domainState?.dns?.pointsHere === true ? 'Готовий' : domainState?.dns?.ok ? 'Інша адреса' : 'Не готовий'} sub={(domainState?.dns?.addresses || []).join(', ') || domainState?.dns?.error || ''} />
            <Metric label="TLS" value={domainRefreshing ? 'Перевіряємо…' : domainState?.tls?.present ? 'Активний' : 'Немає'} sub={domainState?.tls?.expiresAt ? `до ${new Date(domainState.tls.expiresAt).toLocaleDateString('uk-UA')}` : ''} />
          </div>

          {domainState?.error && <div className="error-bar" style={{ marginTop: 14 }}>{domainState.error}</div>}

          <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 16 }}>
            {!domainState?.routePresent && <button className="btn" onClick={connectDomain} disabled={domainBusy || !form.domain.trim() || domainState?.dns?.pointsHere === false || !domainState?.dnsRequirements?.configured}>
              {domainBusy ? 'Підключаємо…' : 'Підключити домен'}
            </button>}
            {domainState?.routePresent && !domainState?.active && <button className="btn" onClick={connectDomain} disabled={domainBusy}>
              {domainBusy ? 'Перевіряємо TLS…' : 'Повторити підключення TLS'}
            </button>}
            {domainState?.routePresent && <button className="btn danger" onClick={disconnectDomain} disabled={domainBusy}>
              {domainBusy ? 'Відключаємо…' : 'Відключити домен'}
            </button>}
            <button className={`btn ghost ${domainRefreshing ? 'is-loading' : ''}`} onClick={() => refreshDomain()} disabled={domainBusy || domainRefreshing}>{domainRefreshing ? 'Перевіряємо…' : 'Оновити статус'}</button>
            {domainState?.active && <a className="btn ghost" href={`https://${selected.domain}/`} target="_blank" rel="noreferrer">Відкрити сайт</a>}
          </div>

          <div className="card" style={{ marginTop: 14, background: 'var(--panel-2, rgba(0,0,0,.12))' }}>
            <strong>Ізоляція</strong>
            <p className="faint" style={{ marginBottom: 0 }}>Панель не має Docker socket, root або shell-доступу. Доменами керує окремий внутрішній Promo Controller: він бачить тільки promo-конфіги, ACME/TLS-сховище та може лише послати nginx сигнал reload. До основної БД він доступу не має.</p>
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
