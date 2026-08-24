import { useEffect, useState } from 'react'

import { api } from '../api'
import { alert, close, confirm, haptic, notify } from '../telegram'

export function Cart({ config, cart, onCartChange, onCheckout }) {
  const [error, setError] = useState('')
  const lines = cart?.lines || []

  const change = async (productId, delta) => {
    haptic('light')
    try {
      await onCartChange(productId, delta)
    } catch (err) {
      setError(err.message)
    }
  }

  const clear = async () => {
    if (!(await confirm('Прибрати всі товари з кошика?'))) return
    try {
      await onCartChange(null, 0, { clear: true })
    } catch (err) {
      setError(err.message)
    }
  }

  if (lines.length === 0) {
    return (
      <div className="empty">
        <h2>Кошик порожній</h2>
        <p>Оберіть щось у каталозі — і сума з'явиться тут.</p>
      </div>
    )
  }

  return (
    <>
      {error && <div className="banner warn">{error}</div>}
      {cart.problems?.length > 0 && (
        <div className="banner warn">
          Змінилася наявність:
          {cart.problems.map((p) => (
            <div key={p}>• {p}</div>
          ))}
        </div>
      )}

      <div className="list" style={{ paddingTop: 12 }}>
        {lines.map((l) => (
          <div className="card" key={l.product_id}>
            <div className="card-body">
              <p className="card-title">{l.name}</p>
              <p className="card-note num">
                {Number(l.price).toFixed(0)} {config.currency} × {l.qty}
              </p>
              <div className="price num">
                {Number(l.line_total).toFixed(0)} <small>{config.currency}</small>
              </div>
            </div>
            <div className="stepper">
              <button onClick={() => change(l.product_id, -1)} aria-label="Прибрати одну">
                −
              </button>
              <span className="qty num">{l.qty}</span>
              <button
                onClick={() => change(l.product_id, 1)}
                disabled={l.qty >= l.stock}
                aria-label="Додати одну"
              >
                +
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="summary">
        <div className="row-between total num">
          <span>До сплати</span>
          <span>
            {Number(cart.subtotal).toFixed(0)} {config.currency}
          </span>
        </div>
      </div>

      <div className="field">
        <button className="secondary" onClick={clear} style={{
          width: '100%', padding: 12, border: 0, borderRadius: 10,
          background: 'transparent', color: 'var(--tg-hint)',
        }}>
          Очистити кошик
        </button>
      </div>
    </>
  )
}

const EMPTY_FORM = {
  contact_surname: '',
  contact_name: '',
  contact_patronymic: '',
  contact_phone: '',
  city: '',
  address: '',
  payment_method: 'card',
  comment: '',
  promo_code: '',
  use_bonus: false,
}

export function Checkout({ config, cart, profile, onDone }) {
  const [form, setForm] = useState(EMPTY_FORM)
  const [promo, setPromo] = useState(null)
  const [checking, setChecking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (profile?.first_name) {
      setForm((f) => (f.contact_name ? f : { ...f, contact_name: profile.first_name }))
    }
  }, [profile])

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }

  const applyPromo = async () => {
    const code = form.promo_code.trim()
    if (!code) return
    setChecking(true)
    try {
      setPromo(await api.checkPromo(code))
    } catch (err) {
      setPromo({ ok: false, error: err.message })
    } finally {
      setChecking(false)
    }
  }

  const subtotal = Number(cart?.subtotal || 0)
  const promoDiscount = promo?.ok ? Number(promo.discount) : 0

  // Знижка за суму й промокод не додаються — діє більша. Так само рахує
  // бекенд, тож підсумок у вітрині збігається з рахунком.
  const volumeDiscount =
    config.volume_discount_enabled &&
    Number(config.volume_discount_min) > 0 &&
    subtotal >= Number(config.volume_discount_min)
      ? Math.round(subtotal * Number(config.volume_discount_percent)) / 100
      : 0
  const discount = Math.max(promoDiscount, volumeDiscount)
  const byVolume = volumeDiscount > promoDiscount
  const bonus = config.bonus_enabled && form.use_bonus
    ? Number(profile?.max_bonus_now || 0) : 0
  const total = Math.max(0, subtotal - discount - bonus)

  const required = ['contact_surname', 'contact_name', 'contact_phone', 'city', 'address']
  const filled = required.every((k) => form[k].trim().length > 0)

  const submit = async () => {
    if (!filled) {
      setError('Заповніть прізвище, імʼя, телефон, місто та адресу.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const order = await api.checkout({
        ...form,
        comment: form.comment.trim() || null,
        promo_code: promo?.ok ? form.promo_code.trim() : null,
      })
      notify('success')
      const payment =
        order.payment_method === 'card' && order.card_number
          ? `\n\nОплата на картку:\n${order.card_number}${
              order.card_holder ? `\n${order.card_holder}` : ''
            }`
          : ''
      alert(
        `Замовлення №${order.order_id} прийнято.\nДо сплати ${Number(order.total).toFixed(
          0,
        )} ${config.currency}.${payment}\n\nДеталі надійдуть у чат з ботом.`,
      )
      onDone()
      close()
    } catch (err) {
      notify('error')
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <>
      <div className="head">
        <h1>Оформлення</h1>
        <p>Куди доставити й на кого оформити</p>
      </div>

      {error && <div className="banner warn">{error}</div>}

      {/* Перевізники вимагають повне ПІБ, тож питаємо трьома полями:
          одним рядком люди вписують його в довільному порядку */}
      <div className="field">
        <label htmlFor="surname">Прізвище</label>
        <input id="surname" className="input" value={form.contact_surname}
               onChange={set('contact_surname')} autoComplete="family-name" />
      </div>

      <div className="field">
        <label htmlFor="name">Імʼя</label>
        <input id="name" className="input" value={form.contact_name}
               onChange={set('contact_name')} autoComplete="given-name" />
      </div>

      <div className="field">
        <label htmlFor="patronymic">По батькові</label>
        <input id="patronymic" className="input" value={form.contact_patronymic}
               onChange={set('contact_patronymic')} autoComplete="additional-name" />
      </div>

      <div className="field">
        <label htmlFor="phone">Телефон</label>
        <input
          id="phone"
          className="input"
          type="tel"
          inputMode="tel"
          placeholder="+380"
          value={form.contact_phone}
          onChange={set('contact_phone')}
        />
      </div>

      <div className="field">
        <label htmlFor="city">Місто</label>
        <input id="city" className="input" value={form.city} onChange={set('city')} />
      </div>

      <div className="field">
        <label htmlFor="address">Відділення або адреса</label>
        <input id="address" className="input" value={form.address} onChange={set('address')} />
      </div>

      <div className="field">
        <label>Спосіб оплати</label>
      </div>
      <div className="choice">
        <button
          aria-pressed={form.payment_method === 'card'}
          onClick={() => setForm((f) => ({ ...f, payment_method: 'card' }))}
        >
          На картку
        </button>
        <button
          aria-pressed={form.payment_method === 'cod'}
          onClick={() => setForm((f) => ({ ...f, payment_method: 'cod' }))}
        >
          Накладений платіж
        </button>
      </div>

      <div className="field">
        <label htmlFor="promo">Промокод</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            id="promo"
            className="input"
            value={form.promo_code}
            onChange={(e) => {
              setPromo(null)
              set('promo_code')(e)
            }}
            placeholder="Якщо є"
          />
          <button className="add" onClick={applyPromo} disabled={checking || !form.promo_code.trim()}>
            {checking ? '…' : 'Застосувати'}
          </button>
        </div>
        {promo && (
          <p className="hint" style={{ marginTop: 6, color: promo.ok ? 'var(--accent)' : 'var(--warn)' }}>
            {promo.ok
              ? `Знижка ${Number(promo.discount).toFixed(0)} ${config.currency}`
              : promo.error}
          </p>
        )}
      </div>

      {config.bonus_enabled && Number(profile?.bonus_balance || 0) > 0 && (
        <label className="toggle">
          <input type="checkbox" checked={form.use_bonus} onChange={set('use_bonus')} />
          <span>
            Списати бонуси
            <br />
            <span className="hint num">
              доступно {Number(profile.max_bonus_now).toFixed(0)} з{' '}
              {Number(profile.bonus_balance).toFixed(0)} {config.currency}
            </span>
          </span>
        </label>
      )}

      <div className="field">
        <label htmlFor="comment">Коментар</label>
        <textarea
          id="comment"
          className="input"
          value={form.comment}
          onChange={set('comment')}
          placeholder="Необовʼязково"
        />
      </div>

      <div className="summary">
        <div className="row-between num">
          <span className="hint">Товари</span>
          <span>
            {subtotal.toFixed(0)} {config.currency}
          </span>
        </div>
        {discount > 0 && (
          <div className="row-between num discount">
            <span>{byVolume ? `Знижка від ${Number(config.volume_discount_min).toFixed(0)}` : 'Промокод'}</span>
            <span>
              −{discount.toFixed(0)} {config.currency}
            </span>
          </div>
        )}
        {bonus > 0 && (
          <div className="row-between num discount">
            <span>Бонуси</span>
            <span>
              −{bonus.toFixed(0)} {config.currency}
            </span>
          </div>
        )}
        <div className="row-between total num">
          <span>До сплати</span>
          <span>
            {total.toFixed(0)} {config.currency}
          </span>
        </div>
      </div>

      <div className="field">
        <button
          className="primary"
          onClick={submit}
          disabled={busy}
          style={{
            width: '100%', padding: 14, border: 0, borderRadius: 10,
            background: 'var(--accent)', color: 'var(--tg-bg)',
            fontSize: 16, fontWeight: 700,
          }}
        >
          {busy ? 'Оформлюємо…' : 'Підтвердити замовлення'}
        </button>
      </div>
    </>
  )
}
