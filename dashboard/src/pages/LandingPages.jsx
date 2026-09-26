import { useEffect, useMemo, useState } from 'react'
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

export default function LandingPages() {
  const notify = useToast()
  const [pages, setPages] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [form, setForm] = useState(newForm())
  const [tab, setTab] = useState('content')
  const [stats, setStats] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)

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
    if (!selected) { setStats(null); return }
    setForm(normalized(selected))
    api.landingPages.stats(selected.id, 30).then(setStats).catch(() => setStats(null))
  }, [selectedId, selected?.version])

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
      const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
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
          <h2 style={{ marginTop: 0 }}>SEO</h2>
          <p className="faint">Шаблон автоматично формує semantic HTML, canonical, Open Graph, Twitter Card і JSON-LD WebPage. Тут змінюються лише дані.</p>
          <div className="grid k2">
            <Field label="Meta title" hint="Орієнтир: до ~60–70 символів."><input className="input" value={form.seo.title} onChange={(e) => setSeo('title', e.target.value)} /></Field>
            <Field label="Canonical URL" hint="Можна лишити порожнім — буде https://домен/."><input className="input" value={form.seo.canonical_url} onChange={(e) => setSeo('canonical_url', e.target.value)} /></Field>
            <Field label="Meta description"><textarea className="input" rows="4" value={form.seo.description} onChange={(e) => setSeo('description', e.target.value)} /></Field>
            <Field label="Keywords" hint="Не впливають напряму на Google ranking, але поле залишене для сумісності/інших систем."><textarea className="input" rows="4" value={form.seo.keywords} onChange={(e) => setSeo('keywords', e.target.value)} /></Field>
            <Field label="Robots"><input className="input" value={form.seo.robots} onChange={(e) => setSeo('robots', e.target.value)} /></Field>
            <Field label="OG locale"><input className="input" value={form.seo.og_locale} onChange={(e) => setSeo('og_locale', e.target.value)} /></Field>
            <Field label="Open Graph title"><input className="input" value={form.seo.og_title} onChange={(e) => setSeo('og_title', e.target.value)} /></Field>
            <Field label="Open Graph description"><textarea className="input" rows="3" value={form.seo.og_description} onChange={(e) => setSeo('og_description', e.target.value)} /></Field>
            <Field label="Site name"><input className="input" value={form.seo.site_name} onChange={(e) => setSeo('site_name', e.target.value)} /></Field>
            <Field label="Schema name"><input className="input" value={form.seo.schema_name} onChange={(e) => setSeo('schema_name', e.target.value)} /></Field>
          </div>
          <ImageField label="OG / social image" value={form.seo.og_image} onChange={(v) => setSeo('og_image', v)} hint="Локальний файл із /media/. Якщо порожньо — використовується фон або логотип." />
          <Field label="Schema description"><textarea className="input" rows="3" value={form.seo.schema_description} onChange={(e) => setSeo('schema_description', e.target.value)} /></Field>
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
          <h2 style={{ marginTop: 0 }}>Домен і публікація</h2>
          <p><strong>Контент редеплоїться одразу кнопкою «Опублікувати»</strong> — без перезапуску API або панелі. Жива сторінка читає production snapshot за доменом.</p>
          <p className="faint">Для нового домену один раз потрібні DNS + TLS + nginx route. Це інфраструктурна операція; вона навмисно не дає панелі Docker socket/root-доступ. Після первинного підключення всі наступні зміни та повторні публікації виконуються з цього модуля.</p>
          <div className="grid k2">
            <Field label="Домен"><input className="input" value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} /></Field>
            <Field label="Production URL"><input className="input" readOnly value={`https://${form.domain || 'domain.example'}/`} /></Field>
          </div>
          <div className="card" style={{ marginTop: 14, background: 'var(--panel-2, rgba(0,0,0,.12))' }}>
            <strong>Потік запиту</strong><p className="faint" style={{ marginBottom: 0 }}>Домен → nginx/TLS → public promo renderer → production snapshot. `/media/` віддається локально nginx; CTA проходить через `/go`, де рахується клік і виконується redirect.</p>
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
