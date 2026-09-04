
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
  // Спосіб доставки. За замовчуванням відділення: ним користується
  // переважна більшість, і курʼєр доступний не всюди.
  delivery_method: 'warehouse',
  // Текст лишається головним: саме його читає менеджер і саме він
  // залишиться осмисленим, коли відділення закриють. Коди — поруч,
  // щоб накладну можна було створити без ручного пошуку.
  city: '',
  delivery_city_ref: '',
  address: '',
  delivery_warehouse_ref: '',
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

  // Довідник Нової пошти. Обраний пункт тримаємо окремо від форми: щоб
  // спитати відділення, потрібні обидва коди — CityRef для міст і
  // SettlementRef для сіл, у яких свого CityRef немає.
  const [cityPick, setCityPick] = useState(null)
  const [cityHits, setCityHits] = useState([])
  const [cityOpen, setCityOpen] = useState(false)
  const [cityBusy, setCityBusy] = useState(false)
  const [points, setPoints] = useState([])
  const [pointsOpen, setPointsOpen] = useState(false)
  const [pointsBusy, setPointsBusy] = useState(false)
  // Довідник відвалився вже після завантаження вітрини. Не показуємо
  // порожній список і не блокуємо оформлення: повертаємось до ручного
  // вводу мовчки. Прийняти замовлення й уточнити адресу в чаті дешевше,
  // ніж втратити покупця через чужу недоступність.
  const [directoryDown, setDirectoryDown] = useState(false)
  // Попередній розрахунок доставки. Живе окремо від суми замовлення й
  // ніколи в неї не входить: платять його перевізникові, а не нам.
  const [shipping, setShipping] = useState(null)
  const directory = Boolean(config.novaposhta_enabled) && !directoryDown
  // Курʼєр вимкнений — вибору немає взагалі. Один варіант краще подати
  // як даність, ніж як вибір із одного: зайва кнопка змушує зупинитись
  // і подумати там, де думати нема над чим.
  const courier = Boolean(config.courier_enabled)
  const toWarehouse = form.delivery_method === 'warehouse' || !courier

  useEffect(() => {
    if (profile?.first_name) {
      setForm((f) => (f.contact_name ? f : { ...f, contact_name: profile.first_name }))
    }
  }, [profile])

  // Пауза перед запитом. Без неї «Дніпро» — це шість звернень до
  // перевізника, по одному на кожну натиснуту літеру.
  useEffect(() => {
    if (!directory || cityPick || !cityOpen) return undefined
    const query = form.city.trim()
    if (query.length < 2) {
      setCityHits([])
      return undefined
    }
    let alive = true
    const timer = setTimeout(async () => {
      setCityBusy(true)
      try {
        const { items } = await api.delivery.cities(query)
        if (alive) setCityHits(items || [])
      } catch (err) {
        if (!alive) return
        setCityHits([])
        // 503 — ключа немає зовсім; питати далі немає сенсу
        if (err.status === 503) setDirectoryDown(true)
      } finally {
        if (alive) setCityBusy(false)
      }
    }, 350)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [form.city, cityOpen, cityPick, directory])

  // Відділення обраного пункту. Фільтр іде тим же запитом: у великому
  // місті їх понад тисячу, і віддавати всі на телефон немає сенсу.
  const pointQuery = form.delivery_warehouse_ref ? '' : form.address.trim()
  useEffect(() => {
    if (!directory || !cityPick || !toWarehouse) {
      setPoints([])
      return undefined
    }
    let alive = true
    const timer = setTimeout(async () => {
      setPointsBusy(true)
      try {
        const { items } = await api.delivery.warehouses(
          cityPick.ref, cityPick.settlement_ref, pointQuery,
        )
        if (alive) setPoints(items || [])
      } catch (err) {
        if (!alive) return
        setPoints([])
        if (err.status === 503) setDirectoryDown(true)
      } finally {
        if (alive) setPointsBusy(false)
      }
    }, 300)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [cityPick, toWarehouse, pointQuery, directory])

  // Рахуємо, щойно відомо куди. Місто — найбільший множник у тарифі,
  // спосіб доставки й накладений платіж міняють суму помітно, тож на
  // кожну зміну питаємо заново.
  // Місто вписали руками — це теж привід показати «від N грн». Раніше
  // розрахунок вимагав вибору з довідника, тож без ключа Нової пошти
  // покупець не бачив узагалі нічого про вартість доставки.
  const hasCity = Boolean(cityPick) || form.city.trim().length > 1
  useEffect(() => {
    if (!hasCity) {
      setShipping(null)
      return undefined
    }
    let alive = true
    const timer = setTimeout(async () => {
      try {
        const data = await api.delivery.price(
          cityPick?.ref || '', cityPick?.settlement_ref || '',
          form.delivery_method, form.payment_method,
        )
        if (alive) setShipping(data)
      } catch {
        // Не порахували — не показуємо нічого. Оформлення це не чіпає.
        if (alive) setShipping(null)
      }
    }, 300)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [cityPick, hasCity, form.delivery_method, form.payment_method])

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }

  // Зміна міста скидає вибране відділення — і в тексті, і в коді. Без
  // цього посилка поїхала б у старе місто з кодом, який там нічого не
  // означає, а помітили б це аж на відправці.
  const changeCity = (e) => {
    const value = e.target.value
    setCityPick(null)
    setCityOpen(true)
    setForm((f) => ({
      ...f, city: value, delivery_city_ref: '',
      address: '', delivery_warehouse_ref: '',
    }))
  }

  const pickCity = (item) => {
    setCityPick({ ref: item.ref, settlement_ref: item.settlement_ref })
    setCityOpen(false)
    setForm((f) => ({
      ...f,
      city: item.label || item.name,
      // Для села CityRef порожній — тоді в замовлення йде код
      // населеного пункту: за ним відділення так само знаходиться.
      delivery_city_ref: item.ref || item.settlement_ref,
      address: '',
      delivery_warehouse_ref: '',
    }))
  }

  const changeAddress = (e) => {
    const value = e.target.value
    setPointsOpen(true)
    setForm((f) => ({ ...f, address: value, delivery_warehouse_ref: '' }))
  }

  const pickPoint = (point) => {
    setPointsOpen(false)
    setForm((f) => ({ ...f, address: point.label, delivery_warehouse_ref: point.ref }))
  }

  const pickMethod = (method) => {
    // Адреса курʼєру й номер відділення — різні речі; лишити попереднє
    // означало б відправити «Відділення №7» як вулицю.
    setPointsOpen(false)
    setForm((f) => ({
      ...f, delivery_method: method, address: '', delivery_warehouse_ref: '',
    }))
  }

  const chosenPoint = points.find((p) => p.ref === form.delivery_warehouse_ref)

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
    // Накладений платіж у поштомат не приймають. Дізнатися про це при
    // спробі забрати посилку — це зіпсоване замовлення й повернення.
    if (chosenPoint?.is_postomat && form.payment_method === 'cod') {
      notify('error')
      setError('У поштоматі накладений платіж не приймають — оберіть '
               + 'відділення або оплату на картку.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const order = await api.checkout({
        ...form,
        // Курʼєра могли вимкнути, поки вкладка була відкрита. Шлемо те,
        // що покупець реально бачив на екрані, інакше замовлення
        // відхилиться з приводу, якого людина не розуміє.
        delivery_method: toWarehouse ? 'warehouse' : 'courier',
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

      {courier && (
        <>
          <div className="field">
            <label>Спосіб доставки</label>
          </div>
          <div className="choice">
            <button
              aria-pressed={toWarehouse}
              onClick={() => pickMethod('warehouse')}
            >
              Відділення
            </button>
            <button
              aria-pressed={!toWarehouse}
              onClick={() => pickMethod('courier')}
            >
              Курʼєр на адресу
            </button>
          </div>
        </>
      )}

      <div className="field combo">
        <label htmlFor="city">Населений пункт</label>
        <input
          id="city"
          className={cls('city')}
          value={form.city}
          onChange={changeCity}
          onFocus={() => setCityOpen(true)}
          onBlur={() => setTouched((t) => ({ ...t, city: true }))}
          autoComplete="off"
          placeholder={directory ? 'Почніть набирати назву' : 'Місто або село'}
        />
        {hint('city')}
        {directory && cityOpen && !cityPick && form.city.trim().length >= 2 && (
          <div className="combo-list">
            {cityBusy && <div className="combo-empty">Шукаємо…</div>}
            {!cityBusy && cityHits.length === 0 && (
              <div className="combo-empty">
                Нічого не знайшлося. Можна вписати руками — менеджер уточнить.
              </div>
            )}
            {cityHits.map((item) => (
              <button
                className="combo-item"
                key={item.settlement_ref || item.ref}
                onClick={() => pickCity(item)}
              >
                <span>{item.label}</span>
                {/* Скільки там відділень — підказка, який із однойменних
                    пунктів потрібен: у міста їх сотні, у села одне */}
                <span className="combo-note num">{item.warehouses}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="field combo">
        <label htmlFor="address">
          {toWarehouse ? 'Відділення або поштомат' : 'Адреса доставки'}
        </label>
        <input
          id="address"
          className={cls('address')}
          value={form.address}
          onChange={changeAddress}
          onFocus={() => setPointsOpen(true)}
          onBlur={() => setTouched((t) => ({ ...t, address: true }))}
          autoComplete="off"
          placeholder={
            toWarehouse ? 'Номер відділення або вулиця' : 'Вулиця, будинок, квартира'
          }
        />
        {hint('address')}
        {toWarehouse && directory && !cityPick && form.city.trim().length > 0 && (
          <p className="hint">
            Оберіть населений пункт зі списку — тоді зʼявиться перелік відділень.
          </p>
        )}
        {toWarehouse && directory && cityPick && pointsOpen
          && !form.delivery_warehouse_ref && (
          <div className="combo-list">
            {pointsBusy && <div className="combo-empty">Завантажуємо відділення…</div>}
            {!pointsBusy && points.length === 0 && (
              <div className="combo-empty">
                Такого відділення немає. Перевірте номер або впишіть адресу руками.
              </div>
            )}
            {points.map((point) => (
              <button className="combo-item" key={point.ref} onClick={() => pickPoint(point)}>
                <span>{point.label}</span>
                {point.is_postomat && <span className="combo-tag">поштомат</span>}
              </button>
            ))}
          </div>
        )}
        {chosenPoint && (
          <p className="combo-picked">
            Обрано: {chosenPoint.short || chosenPoint.label}
          </p>
        )}
        {/* Поштомат не приймає накладений платіж — про це краще сказати
            тут, ніж дізнатися при спробі забрати посилку */}
        {chosenPoint?.is_postomat && form.payment_method === 'cod' && (
          <p className="field-error">
            У поштоматі накладений платіж не приймають. Оберіть відділення
            або оплату на картку.
          </p>
        )}
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

        {/* Доставка стоїть ПІСЛЯ підсумку і поза ним навмисно. Її платять
            перевізникові на відділенні, а не нам — вписати її в «До
            сплати» означало б показати суму, якої покупець нам не
            переказує. */}
        {shipping && (shipping.cost || shipping.cost_from > 0) && (
          <div className="shipping">
            <div className="row-between num">
              <span className="hint">
                Доставка{shipping.source === 'novaposhta' ? ' Новою поштою' : ''}
              </span>
              <span>
                {shipping.cost
                  ? `≈ ${shipping.cost} ${config.currency}`
                  : `від ${shipping.cost_from.toFixed(0)} ${config.currency}`}
              </span>
            </div>
            {shipping.redelivery > 0 && (
              <div className="row-between num">
                <span className="hint">Переказ накладеного платежу</span>
                <span>≈ {shipping.redelivery} {config.currency}</span>
              </div>
            )}
            {/* Слово «приблизно» тут не осторога заради остороги.
                Перевізник рахує за фактичною вагою й габаритами, а їх
                дізнаються лише коли посилку зважать на відділенні. Ми
                підставляємо припущену вагу — тож це орієнтир. */}
            <p className="shipping-note">
              {shipping.source === 'novaposhta'
                ? `Попередній розрахунок Нової пошти за вагою ${shipping.weight} кг.`
                : 'Приблизна вартість.'}
              {' '}Точну суму називає перевізник при відправці — уточніть
              її в менеджера. Оплачується окремо, у підсумок вище не
              входить.
            </p>
          </div>
        )}
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
