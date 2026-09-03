
/** Український номер у єдиному вигляді.
 *
 *  Люди вводять по-різному: 0671112233, 380671112233, +38 (067) 111-22-33.
 *  Нормалізуємо все до +380XXXXXXXXX, а не сваримось за формат — виправити
 *  за людину дешевше, ніж пояснювати їй правило.
 */
export function normalizePhone(raw) {
  const digits = String(raw || '').replace(/\D/g, '')
  if (!digits) return ''

  let body = digits
  if (body.startsWith('380')) body = body.slice(3)
  else if (body.startsWith('80')) body = body.slice(2)
  else if (body.startsWith('0')) body = body.slice(1)

  return '+380' + body.slice(0, 9)
}

/** Текст помилки або порожньо, якщо все гаразд. */
export function phoneError(value) {
  const digits = String(value || '').replace(/\D/g, '')
  if (!digits) return 'Вкажіть номер телефону'
  const body = digits.startsWith('380') ? digits.slice(3) : digits
  if (body.length < 9) return `Бракує цифр: ${9 - body.length}`
  if (body.length > 9) return 'Забагато цифр — в українському номері їх дев\u2019ять'
  // Українські мобільні коди починаються з 3–9 (039, 050, 063, 066…).
  // Нуль чи одиниця на цьому місці означає, що людина набрала зайвий
  // префікс — краще сказати про це одразу, ніж отримати недзвінкий номер.
  if (!/^[3-9]/.test(body)) return 'Схоже на помилку в коді оператора'
  return ''
}

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

export function Checkout({ config, cart, profile, onDone, onLegal }) {
  const [form, setForm] = useState(EMPTY_FORM)
  const [promo, setPromo] = useState(null)
  const [checking, setChecking] = useState(false)
  const [busy, setBusy] = useState(false)
  // Помилку показуємо лише після того, як поле покинули: підсвічувати
  // порожній номер, поки людина його ще набирає, — це причіпка, а не поміч.
  const [touched, setTouched] = useState({})
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

  // Порядок збігається з порядком полів на екрані: за ним ведемо людину
  // до першого незаповненого, а не до випадкового.
  const REQUIRED = [
    ['contact_surname', 'surname', 'Вкажіть прізвище'],
    ['contact_name', 'name', 'Вкажіть імʼя'],
    ['contact_phone', 'phone', 'Вкажіть телефон'],
    ['city', 'city', 'Вкажіть місто'],
    ['address', 'address', 'Вкажіть відділення або адресу'],
  ]
  const missing = REQUIRED.filter(([key]) => !form[key].trim())
  const filled = missing.length === 0

  const submit = async () => {
    if (!filled) {
      // Раніше тут був один банер з переліком усіх пʼяти полів, а
      // підсвічувався лише телефон. Людина читала речення й сама шукала
      // очима, яке саме поле пропустила — на телефоні, де на екран
      // вміщається два поля з семи. Тепер помічаємо всі порожні одразу
      // і прокручуємо до першого.
      setTouched((t) => ({
        ...t, ...Object.fromEntries(REQUIRED.map(([key]) => [key, true])),
      }))
      setError('')
      const [, id] = missing[0]
      const node = document.getElementById(id)
      if (node) {
        node.scrollIntoView({ behavior: 'smooth', block: 'center' })
        // Фокус після прокрутки: інакше Telegram піднімає клавіатуру
        // й гасить саму прокрутку на півдорозі.
        setTimeout(() => node.focus({ preventScroll: true }), 300)
      }
      notify('error')
      return
    }
    const phoneProblem = phoneError(form.contact_phone)
    if (phoneProblem) {
      setTouched((t) => ({ ...t, contact_phone: true }))
      setError(`Телефон: ${phoneProblem.toLowerCase()}`)
      const node = document.getElementById('phone')
      if (node) node.scrollIntoView({ behavior: 'smooth', block: 'center' })
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

  // Обовʼязкове поле, яке лишили порожнім. Один помічник на всі — інакше
  // підсвітка з часом розійдеться: у телефона вона була, у решти ні.
  const blank = (key) => touched[key] && !form[key].trim()
  const cls = (key) => `input ${blank(key) ? 'bad' : ''}`
  const hint = (key) => {
    const found = REQUIRED.find(([k]) => k === key)
    return blank(key) && found ? <div className="field-error">{found[2]}</div> : null
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
        <input id="surname" className={cls('contact_surname')}
               value={form.contact_surname}
               onChange={set('contact_surname')} autoComplete="family-name" />
        {hint('contact_surname')}
      </div>

      <div className="field">
        <label htmlFor="name">Імʼя</label>
        <input id="name" className={cls('contact_name')} value={form.contact_name}
               onChange={set('contact_name')} autoComplete="given-name" />
        {hint('contact_name')}
      </div>

      <div className="field">
        <label htmlFor="patronymic">
          По батькові <span className="faint">— не обовʼязково</span>
        </label>
        <input id="patronymic" className="input" value={form.contact_patronymic}
               onChange={set('contact_patronymic')} autoComplete="additional-name" />
      </div>

      <div className="field">
        <label htmlFor="phone">Телефон</label>
        <input
          id="phone"
          className={`input ${
            touched.contact_phone
            && (blank('contact_phone') || phoneError(form.contact_phone)) ? 'bad' : ''
          }`}
          type="tel"
          inputMode="tel"
          placeholder="+380XXXXXXXXX"
          value={form.contact_phone}
          onFocus={() => {
            // Підставляємо префікс одразу: так одразу видно, що чекають
            // український номер, і людина не почне з нуля чи вісімки.
            if (!form.contact_phone) setForm((f) => ({ ...f, contact_phone: '+380' }))
          }}
          onChange={(e) => setForm((f) => ({
            ...f, contact_phone: normalizePhone(e.target.value),
          }))}
          onBlur={() => setTouched((t) => ({ ...t, contact_phone: true }))}
        />
        {hint('contact_phone')}
        {touched.contact_phone && !blank('contact_phone')
          && phoneError(form.contact_phone) && (
          <div className="field-error">{phoneError(form.contact_phone)}</div>
        )}
      </div>

      <div className="field">
        <label htmlFor="city">Місто</label>
        <input id="city" className={cls('city')} value={form.city}
               onChange={set('city')} />
        {hint('city')}
      </div>

      <div className="field">
        <label htmlFor="address">Відділення або адреса</label>
        <input id="address" className={cls('address')} value={form.address}
               onChange={set('address')} />
        {hint('address')}
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

      {/* Згода з офертою — умова укладення договору за ст. 633 ЦК України,
          тож посилання має бути саме тут, перед підтвердженням */}
      <p className="hint" style={{ padding: '0 14px 10px' }}>
        Підтверджуючи замовлення, ви приймаєте{' '}
        <button className="inline-link" onClick={() => onLegal?.('offer')}>
          умови публічної оферти
        </button>{' '}
        і погоджуєтесь на{' '}
        <button className="inline-link" onClick={() => onLegal?.('privacy')}>
          обробку персональних даних
        </button>. Умови{' '}
        <button className="inline-link" onClick={() => onLegal?.('returns')}>
          повернення та обміну
        </button>.
      </p>

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
