import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../api'
import { promoDateInput, promoPayload, validatePromoForm } from '../promoForm'
import {
  Empty,
  ErrorBar,
  Field,
  Loading,
  Modal,
  confirmPurge,
  money,
  useToast,
} from '../components/ui'
import './promos.css'

const EMPTY = {
  code: '',
  type: 'percent',
  value: '',
  min_order: 0,
  max_uses: '',
  per_user_limit: 1,
  is_active: true,
  category_ids: [],
}
const STATUS = {
  active: ['Активний', 'ok'],
  inactive: ['Вимкнений', ''],
  expired: ['Прострочений', 'bad'],
  exhausted: ['Вичерпаний', 'warn'],
}
const expiryDate = (value) => {
  return promoDateInput(value)
}
const statusOf = (promo) =>
  !promo.is_active
    ? 'inactive'
    : promo.expires_at && new Date(promo.expires_at) < new Date()
      ? 'expired'
      : promo.max_uses != null && promo.used_count >= promo.max_uses
        ? 'exhausted'
        : 'active'
const discountLabel = (promo) =>
  promo.type === 'percent'
    ? `${Number(promo.value || 0)}%`
    : money(promo.value || 0)
const categoryLabel = (id, categories) =>
  categories.find((c) => c.id === id)?.name || `Категорія #${id}`

const usesLabel = (count) => {
  const last = count % 10,
    lastTwo = count % 100
  return `${count} ${last === 1 && lastTwo !== 11 ? 'раз' : last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? 'рази' : 'разів'}`
}

function PromoIcon({ kind }) {
  return (
    <svg
      width="17"
      height="17"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {kind === 'plus' ? (
        <path d="M12 5v14M5 12h14" />
      ) : kind === 'copy' ? (
        <>
          <rect x="8" y="8" width="12" height="13" rx="2" />
          <path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" />
        </>
      ) : (
        <>
          <path d="M3 6h18M9 6V4h6v2M5 6l1 15h12l1-15M10 10v7M14 10v7" />
        </>
      )}
    </svg>
  )
}

function PromoForm({
  promo,
  categories,
  categoryError,
  reloadCategories,
  onClose,
  onSaved,
}) {
  const notify = useToast()
  const saving = useRef(false)
  const initialDate = expiryDate(promo?.expires_at)
  const [form, setForm] = useState({
    ...EMPTY,
    ...promo,
    expires_on: initialDate,
    max_uses: promo?.max_uses ?? '',
    category_ids: [...(promo?.category_ids || [])],
  })
  const [scope, setScope] = useState(
    promo?.category_ids?.length ? 'categories' : 'all',
  )
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const validation = validatePromoForm({ ...form, expires_at: form.expires_on })
  const validCode = !validation.code
  const validAmount = !validation.value && !validation.min_order
  const validLimits =
    !validation.max_uses && !validation.per_user_limit && !validation.expires_at
  const selected = new Set(form.category_ids)
  const visible = (categories || []).filter((c) =>
    c.name
      .toLocaleLowerCase('uk')
      .includes(search.trim().toLocaleLowerCase('uk')),
  )
  const missing = form.category_ids.filter(
    (id) => !categories?.some((c) => c.id === id),
  )
  const set = (key) => (event) =>
    setForm((f) => ({
      ...f,
      [key]:
        event.target.type === 'checkbox'
          ? event.target.checked
          : event.target.value,
    }))
  const toggle = (id) =>
    setForm((f) => ({
      ...f,
      category_ids: f.category_ids.includes(id)
        ? f.category_ids.filter((value) => value !== id)
        : [...f.category_ids, id],
    }))
  const generate = () => {
    const values = crypto.getRandomValues(new Uint8Array(6))
    setForm((f) => ({
      ...f,
      code: `ELFAR${[...values].map((v) => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[v % 32]).join('')}`,
    }))
  }
  const close = () => {
    if (!saving.current) onClose()
  }
  const save = async (event) => {
    event.preventDefault()
    if (saving.current) return
    if (Object.keys(validation).length) {
      setError(Object.values(validation)[0])
      return
    }
    if (
      scope === 'categories' &&
      (!selected.size || !categories || categoryError || missing.length)
    ) {
      setError(
        'Виберіть хоча б одну доступну категорію. Видалені категорії потрібно прибрати з вибору.',
      )
      return
    }
    saving.current = true
    setBusy(true)
    setError('')
    const payload = promoPayload(
      {
        ...form,
        expires_at: form.expires_on,
        category_ids: scope === 'categories' ? form.category_ids : [],
      },
      promo,
    )
    try {
      promo?.id
        ? await api.promos.update(promo.id, payload)
        : await api.promos.create(payload)
      notify(promo?.id ? 'Промокод оновлено' : 'Промокод створено')
      onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  return (
    <Modal
      title={promo?.id ? 'Редагувати промокод' : 'Новий промокод'}
      className="promo-modal"
      onClose={close}
      footer={
        <>
          <span className="promo-footer-note">
            {form.is_active
              ? 'Умови застосуються після збереження'
              : 'Збережеться вимкненим'}
          </span>
          <button className="btn ghost" disabled={busy} onClick={close}>
            Скасувати
          </button>
          <button
            className="btn"
            type="submit"
            form="promo-editor"
            disabled={
              busy ||
              !validCode ||
              !validAmount ||
              !validLimits ||
              (scope === 'categories' &&
                (!selected.size ||
                  !categories ||
                  !!categoryError ||
                  !!missing.length))
            }
          >
            {busy
              ? 'Зберігаємо…'
              : promo?.id
                ? 'Зберегти зміни'
                : 'Створити промокод'}
          </button>
        </>
      }
    >
      <form id="promo-editor" className="promo-editor" onSubmit={save}>
        <ErrorBar error={error} />
        <fieldset disabled={busy} className="promo-form-fields">
          <div className="promo-form-main">
            <section className="promo-section" aria-labelledby="promo-basics">
              <div className="promo-section-title">
                <span>01</span>
                <div>
                  <h3 id="promo-basics">Код і знижка</h3>
                  <p>Налаштуйте пропозицію для клієнтів</p>
                </div>
              </div>
              <Field
                label="Промокод"
                hint="2–32 символи, без пробілів. Регістр не має значення."
              >
                <div className="promo-code-input">
                  <input
                    className="input mono"
                    aria-label="Промокод"
                    required
                    minLength={2}
                    maxLength={32}
                    pattern="[^\s]+"
                    placeholder="Наприклад, WELCOME10"
                    value={form.code}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        code: e.target.value.toUpperCase(),
                      }))
                    }
                  />
                  <button
                    className="btn ghost"
                    type="button"
                    onClick={generate}
                  >
                    Згенерувати
                  </button>
                </div>
              </Field>
              <div
                className="promo-type-picker"
                role="group"
                aria-label="Тип знижки"
              >
                {[
                  ['percent', 'Відсоток', '% від вартості'],
                  ['fixed', 'Фіксована сума', 'Знижка у гривнях'],
                ].map(([type, title, hint]) => (
                  <label
                    key={type}
                    className={form.type === type ? 'selected' : ''}
                  >
                    <input
                      type="radio"
                      name="promo-type"
                      value={type}
                      checked={form.type === type}
                      onChange={set('type')}
                    />
                    <span>
                      <strong>{title}</strong>
                      <small>{hint}</small>
                    </span>
                  </label>
                ))}
              </div>
              <div className="grid k2">
                <Field
                  label={
                    form.type === 'percent'
                      ? 'Розмір знижки, %'
                      : 'Розмір знижки, ₴'
                  }
                >
                  <input
                    className="input"
                    aria-label="Розмір знижки"
                    type="number"
                    required
                    min="0.01"
                    max={form.type === 'percent' ? 100 : 9999999999.99}
                    step="0.01"
                    placeholder={form.type === 'percent' ? '10' : '100'}
                    value={form.value}
                    onChange={set('value')}
                  />
                </Field>
                <Field
                  label="Замовлення від, ₴"
                  hint="0 — без мінімальної суми"
                >
                  <input
                    className="input"
                    aria-label="Мінімальна сума замовлення"
                    type="number"
                    required
                    min="0"
                    max="9999999999.99"
                    step="0.01"
                    value={form.min_order}
                    onChange={set('min_order')}
                  />
                </Field>
              </div>
              {form.type === 'percent' && Number(form.value) > 100 && (
                <p className="promo-validation" role="alert">
                  Відсоткова знижка не може перевищувати 100%.
                </p>
              )}
            </section>
            <section className="promo-section" aria-labelledby="promo-scope">
              <div className="promo-section-title">
                <span>02</span>
                <div>
                  <h3 id="promo-scope">На які товари діє</h3>
                  <p>
                    Знижка поширюється на всі товари обраних категорій та їхніх
                    підкатегорій
                  </p>
                </div>
              </div>
              <div
                className="promo-scope-picker"
                role="group"
                aria-label="Область дії промокоду"
              >
                <label className={scope === 'all' ? 'selected' : ''}>
                  <input
                    type="radio"
                    name="promo-scope"
                    checked={scope === 'all'}
                    onChange={() => setScope('all')}
                  />
                  Усі товари
                </label>
                <label className={scope === 'categories' ? 'selected' : ''}>
                  <input
                    type="radio"
                    name="promo-scope"
                    checked={scope === 'categories'}
                    onChange={() => setScope('categories')}
                  />
                  Обрані категорії
                </label>
              </div>
              {scope === 'categories' && (
                <div className="promo-category-picker">
                  <ErrorBar error={categoryError} />
                  {categoryError ? (
                    <button
                      type="button"
                      className="btn ghost small"
                      onClick={reloadCategories}
                    >
                      Завантажити категорії повторно
                    </button>
                  ) : !categories ? (
                    <Loading rows={2} />
                  ) : (
                    <>
                      <input
                        className="input"
                        type="search"
                        aria-label="Пошук категорій"
                        placeholder="Знайти категорію…"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                      <div className="promo-category-tools">
                        <span>Обрано: {selected.size}</span>
                        <button
                          type="button"
                          disabled={!visible.length}
                          onClick={() =>
                            setForm((f) => ({
                              ...f,
                              category_ids: [
                                ...new Set([
                                  ...f.category_ids,
                                  ...visible.map((c) => c.id),
                                ]),
                              ],
                            }))
                          }
                        >
                          Вибрати знайдені
                        </button>
                        <button
                          type="button"
                          disabled={!selected.size}
                          onClick={() =>
                            setForm((f) => ({ ...f, category_ids: [] }))
                          }
                        >
                          Очистити
                        </button>
                      </div>
                      <div
                        className="promo-category-list"
                        aria-label="Категорії товарів"
                      >
                        {visible.map((c) => (
                          <label
                            key={c.id}
                            className={selected.has(c.id) ? 'selected' : ''}
                          >
                            <input
                              type="checkbox"
                              checked={selected.has(c.id)}
                              onChange={() => toggle(c.id)}
                            />
                            <span>
                              {c.name}
                              {!c.is_active && (
                                <small>Прихована категорія</small>
                              )}
                            </span>
                            <small>{c.products_count || 0} тов.</small>
                          </label>
                        ))}
                        {!visible.length && (
                          <p className="muted">
                            {categories.length
                              ? 'Категорій за цим запитом немає'
                              : 'Спочатку створіть категорії в каталозі'}
                          </p>
                        )}
                      </div>
                      {!!selected.size && (
                        <div className="promo-selected-categories">
                          {form.category_ids.map((id) => (
                            <button
                              type="button"
                              key={id}
                              className={`chip ${missing.includes(id) ? 'bad' : 'info'}`}
                              onClick={() => toggle(id)}
                              aria-label={`Прибрати категорію ${categoryLabel(id, categories)}`}
                            >
                              {categoryLabel(id, categories)}{' '}
                              <span aria-hidden="true">×</span>
                            </button>
                          ))}
                        </div>
                      )}
                      {!!missing.length && (
                        <p className="promo-validation" role="alert">
                          Приберіть видалені категорії або змініть область дії.
                        </p>
                      )}
                    </>
                  )}
                </div>
              )}
            </section>
            <section className="promo-section" aria-labelledby="promo-limits">
              <div className="promo-section-title">
                <span>03</span>
                <div>
                  <h3 id="promo-limits">Термін і ліміти</h3>
                  <p>Контролюйте кількість використань</p>
                </div>
              </div>
              <div className="grid k2">
                <Field
                  label="Загальний ліміт"
                  hint={
                    promo?.used_count
                      ? `Уже використано: ${promo.used_count}`
                      : 'Порожньо — без обмежень'
                  }
                >
                  <input
                    className="input"
                    aria-label="Загальний ліміт"
                    type="number"
                    min="1"
                    max="2147483647"
                    step="1"
                    placeholder="Без ліміту"
                    value={form.max_uses}
                    onChange={set('max_uses')}
                  />
                </Field>
                <Field label="На одного клієнта">
                  <input
                    className="input"
                    aria-label="На одного клієнта"
                    type="number"
                    required
                    min="1"
                    max="2147483647"
                    step="1"
                    value={form.per_user_limit}
                    onChange={set('per_user_limit')}
                  />
                </Field>
                <Field
                  label="Діє до"
                  hint="Включно з обраним днем за часом Києва. Порожньо — безстроково."
                >
                  <input
                    className="input"
                    aria-label="Діє до"
                    type="date"
                    max="9998-12-31"
                    value={form.expires_on}
                    onChange={set('expires_on')}
                  />
                </Field>
              </div>
              <label className="promo-active-toggle">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={set('is_active')}
                />
                <span>
                  <strong>Промокод активний</strong>
                  <small>
                    Клієнти можуть використовувати код після збереження
                  </small>
                </span>
              </label>
            </section>
          </div>
          <aside className="promo-preview" aria-label="Підсумок промокоду">
            <span className="promo-eyebrow">ВАША ПРОПОЗИЦІЯ</span>
            <div className="promo-preview-discount">−{discountLabel(form)}</div>
            <div className="promo-preview-code mono">
              {form.code.trim() || 'ВАШ ПРОМОКОД'}
            </div>
            <div className="promo-preview-details">
              <p>
                <span>Область дії</span>
                <strong>
                  {scope === 'all'
                    ? 'Усі товари магазину'
                    : `Обрано категорій: ${selected.size}`}
                </strong>
              </p>
              <p>
                <span>Мінімальне замовлення</span>
                <strong>
                  {Number(form.min_order) > 0
                    ? money(form.min_order)
                    : 'Без мінімуму'}
                </strong>
              </p>
              <p>
                <span>Використання</span>
                <strong>
                  {form.max_uses || 'Без ліміту'} · на клієнта:{' '}
                  {form.per_user_limit || '—'}
                </strong>
              </p>
              <p>
                <span>Термін дії</span>
                <strong>
                  {form.expires_on
                    ? form.expires_on.split('-').reverse().join('.')
                    : 'Безстроково'}
                </strong>
              </p>
            </div>
            <span className={`chip ${form.is_active ? 'ok' : ''}`}>
              {form.is_active ? 'Увімкнений' : 'Вимкнений'}
            </span>
            <p className="promo-preview-hint">
              {scope === 'categories'
                ? 'Знижка розраховується лише від вартості товарів обраних категорій. Мінімальна сума перевіряється за всім кошиком.'
                : 'Знижка розраховується від вартості всіх товарів кошика.'}{' '}
              Фіксована знижка не перевищить вартість відповідних товарів.
            </p>
          </aside>
        </fieldset>
      </form>
    </Modal>
  )
}

export default function Promos() {
  const notify = useToast()
  const [promos, setPromos] = useState(null)
  const [categories, setCategories] = useState(null)
  const [categoryError, setCategoryError] = useState('')
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [pending, setPending] = useState(null)
  const [now, setNow] = useState(Date.now())
  const load = useCallback(async () => {
    setError('')
    try {
      setPromos(await api.promos.list())
    } catch (err) {
      setError(err.message)
    }
  }, [])
  const loadCategories = useCallback(async () => {
    setCategoryError('')
    try {
      setCategories(await api.categories.list())
    } catch (err) {
      setCategoryError(err.message)
    }
  }, [])
  useEffect(() => {
    load()
    loadCategories()
    const tick = setInterval(() => setNow(Date.now()), 30000)
    return () => clearInterval(tick)
  }, [load, loadCategories])
  const counts = useMemo(
    () =>
      (promos || []).reduce(
        (acc, p) => {
          acc[statusOf(p)]++
          acc.uses += p.used_count
          return acc
        },
        { active: 0, inactive: 0, expired: 0, exhausted: 0, uses: 0 },
      ),
    [promos, now],
  )
  const visible = (promos || []).filter(
    (p) =>
      (filter === 'all' || statusOf(p) === filter) &&
      `${p.code} ${(p.category_ids || []).map((id) => categoryLabel(id, categories || [])).join(' ')}`
        .toLocaleLowerCase('uk')
        .includes(query.trim().toLocaleLowerCase('uk')),
  )
  const action = async (p, kind) => {
    if (pending !== null) return
    if (kind === 'deactivate' && !confirm(`Вимкнути промокод ${p.code}?`))
      return
    if (
      kind === 'purge' &&
      !confirmPurge(
        p.code,
        p.used_count
          ? `Разом з ним зникне історія застосувань (${p.used_count}).`
          : '',
      )
    )
      return
    setPending(p.id)
    try {
      if (kind === 'purge') await api.promos.purge(p.id)
      else if (kind === 'deactivate') await api.promos.remove(p.id)
      else
        await api.promos.update(p.id, promoPayload({
          ...p, expires_at: expiryDate(p.expires_at), max_uses: p.max_uses ?? '', is_active: true,
        }, p))
      notify(
        kind === 'purge'
          ? 'Промокод стерто назавжди'
          : kind === 'deactivate'
            ? 'Промокод вимкнено'
            : 'Промокод увімкнено',
      )
      await load()
    } catch (err) {
      notify(err.message, 'bad')
    } finally {
      setPending(null)
    }
  }
  const copy = async (code) => {
    try {
      await navigator.clipboard.writeText(code)
      notify('Код скопійовано')
    } catch {
      notify('Не вдалося скопіювати. Виділіть код вручну.', 'bad')
    }
  }

  return (
    <div className="promos-page">
      <div className="page-head">
        <div>
          <h1>Промокоди</h1>
          <p>Керуйте знижками, категоріями та умовами використання</p>
        </div>
        <button className="btn" onClick={() => setEditing({})}>
          <PromoIcon kind="plus" /> Створити промокод
        </button>
      </div>
      <ErrorBar error={error} />
      {error && (
        <button className="btn ghost small" onClick={load}>
          Спробувати ще раз
        </button>
      )}
      {promos && (
        <div className="promo-stats">
          <div>
            <span>Усього промокодів</span>
            <strong>{promos.length}</strong>
          </div>
          <div>
            <span>Активні зараз</span>
            <strong className="promo-stat-active">{counts.active}</strong>
          </div>
          <div>
            <span>Завершені або вичерпані</span>
            <strong>{counts.expired + counts.exhausted}</strong>
          </div>
          <div>
            <span>Використань</span>
            <strong>{counts.uses}</strong>
          </div>
        </div>
      )}
      <div className="promo-toolbar">
        <input
          className="input"
          type="search"
          aria-label="Пошук промокодів"
          placeholder="Знайти код або категорію…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="input"
          aria-label="Статус промокодів"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">Усі статуси</option>
          {Object.entries(STATUS).map(([value, [label]]) => (
            <option key={value} value={value}>
              {label} · {counts[value]}
            </option>
          ))}
        </select>
        <span className="muted">Знайдено: {visible.length}</span>
      </div>
      {!promos ? (
        !error && <Loading />
      ) : !promos.length ? (
        <Empty title="Створіть першу пропозицію">
          Додайте вітальну знижку або промокод на окремі категорії.
        </Empty>
      ) : !visible.length ? (
        <Empty title="Промокодів за цими умовами немає">
          <button
            className="btn ghost small"
            onClick={() => {
              setQuery('')
              setFilter('all')
            }}
          >
            Скинути пошук і фільтр
          </button>
        </Empty>
      ) : (
        <div className="promo-cards">
          {visible.map((p) => {
            const [label, tone] = STATUS[statusOf(p)]
            const ids = p.category_ids || []
            return (
              <article key={p.id} className="promo-card">
                <div className="promo-card-top">
                  <span className={`chip ${tone}`}>{label}</span>
                  <span className="promo-card-discount">
                    −{discountLabel(p)}
                  </span>
                </div>
                <div className="promo-card-code">
                  <strong className="mono">{p.code}</strong>
                  <button
                    className="icon-btn"
                    title="Копіювати код"
                    aria-label={`Копіювати ${p.code}`}
                    onClick={() => copy(p.code)}
                  >
                    <PromoIcon kind="copy" />
                  </button>
                </div>
                <div className="promo-card-scope">
                  <span className="muted">Діє на</span>
                  <div>
                    {ids.length ? (
                      <>
                        {ids.slice(0, 3).map((id) => (
                          <span key={id} className="chip">
                            {categoryLabel(id, categories || [])}
                          </span>
                        ))}
                        {ids.length > 3 && (
                          <span
                            className="chip"
                            title={ids
                              .slice(3)
                              .map((id) => categoryLabel(id, categories || []))
                              .join(', ')}
                          >
                            Ще {ids.length - 3}
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="chip">Усі товари</span>
                    )}
                  </div>
                </div>
                <dl className="promo-card-details">
                  <div>
                    <dt>Замовлення від</dt>
                    <dd>
                      {Number(p.min_order) > 0
                        ? money(p.min_order)
                        : 'Будь-якої суми'}
                    </dd>
                  </div>
                  <div>
                    <dt>На клієнта</dt>
                    <dd>{usesLabel(p.per_user_limit)}</dd>
                  </div>
                  <div>
                    <dt>Діє до</dt>
                    <dd>
                      {p.expires_at
                        ? expiryDate(p.expires_at)
                            .split('-')
                            .reverse()
                            .join('.')
                        : 'Безстроково'}
                    </dd>
                  </div>
                  <div>
                    <dt>Використано</dt>
                    <dd>
                      {p.used_count}
                      {p.max_uses != null ? ` / ${p.max_uses}` : ' / ∞'}
                    </dd>
                  </div>
                </dl>
                {p.max_uses != null && (
                  <progress
                    className="promo-usage"
                    max={p.max_uses}
                    value={Math.min(p.used_count, p.max_uses)}
                    aria-label={`Використання ${p.code}`}
                  />
                )}
                <div className="promo-card-actions">
                  <button
                    className="btn ghost small"
                    disabled={pending !== null}
                    onClick={() => setEditing(p)}
                  >
                    Редагувати
                  </button>
                  <button
                    className="btn ghost small"
                    disabled={pending !== null}
                    title="Створити новий код з такими самими умовами"
                    onClick={() =>
                      setEditing({
                        ...p,
                        id: undefined,
                        used_count: 0,
                        code: `${p.code.slice(0, 26)}-COPY`,
                        is_active: false,
                      })
                    }
                  >
                    Дублювати
                  </button>
                  <button
                    className="btn ghost small"
                    disabled={pending !== null}
                    onClick={() =>
                      action(p, p.is_active ? 'deactivate' : 'activate')
                    }
                  >
                    {pending === p.id
                      ? 'Зачекайте…'
                      : p.is_active
                        ? 'Вимкнути'
                        : 'Увімкнути'}
                  </button>
                  <button
                    className="icon-btn promo-delete"
                    disabled={pending !== null}
                    title="Стерти назавжди"
                    aria-label={`Стерти ${p.code}`}
                    onClick={() => action(p, 'purge')}
                  >
                    <PromoIcon kind="delete" />
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      )}
      {editing && (
        <PromoForm
          promo={editing}
          categories={categories}
          categoryError={categoryError}
          reloadCategories={loadCategories}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </div>
  )
}
