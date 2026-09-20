import { useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { confirm, haptic, notify, openLink } from '../telegram'

const STATUS = {
  new: 'Нове',
  confirmed: 'Підтверджено',
  accepted: 'Прийнято в роботу',
  paid: 'Оплачено',
  shipped: 'Відправлено',
  done: 'Виконано',
  cancelled: 'Скасовано',
}

export function Profile({ config, profile }) {
  const [orders, setOrders] = useState(null)
  const [copied, setCopied] = useState(false)
  // Номер замовлення, яке саме скасовується. Не булеве значення: із
  // кількома замовленнями на екрані треба знати, на якій саме кнопці
  // показувати очікування.
  const [cancelling, setCancelling] = useState(null)
  const cancellingRef = useRef(null)
  const [cancelError, setCancelError] = useState('')

  useEffect(() => {
    api.orders().then(setOrders).catch(() => setOrders([]))
  }, [])

  const cancel = async (order) => {
    // Ref ставимо ДО confirm(): два дуже швидкі тапи інакше відкривають
    // два нативні діалоги ще до того, як React встигне перемалювати disabled.
    if (cancellingRef.current !== null) return
    cancellingRef.current = order.id
    setCancelling(order.id)
    try {
      // Питаємо підтвердження нативним вікном Telegram: скасування
      // повертає товар на склад і бонуси на рахунок, відкотити його
      // назад покупець уже не зможе.
      const sure = await confirm(
        `Скасувати замовлення №${order.id}? Повернути його потім не вийде — `
        + 'доведеться оформити наново.',
      )
      if (!sure) return

      setCancelError('')
      const data = await api.cancelOrder(order.id)
      setOrders(data.orders)
      notify('success')
    } catch (err) {
      // Найчастіша причина — менеджер устиг узяти замовлення в роботу
      // між тим, як екран намалювався, і натисканням кнопки.
      setCancelError(err.message)
      notify('error')
    } finally {
      cancellingRef.current = null
      setCancelling(null)
    }
  }

  const share = () => {
    haptic('light')
    if (!profile?.referral_link) return
    // Нативний шер Telegram: одразу відкриває вибір чату
    openLink(
      `https://t.me/share/url?url=${encodeURIComponent(profile.referral_link)}` +
        `&text=${encodeURIComponent('Раджу цей магазин')}`,
    )
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(profile.referral_link)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      share()
    }
  }

  if (!profile) return <div className="list"><div className="skeleton" /></div>

  return (
    <>
      <div className="head">
        <h1>Профіль</h1>
        <p>Бонуси, запрошення та історія замовлень</p>
      </div>

      <div className="stats">
        {config.bonus_enabled && (
          <div className="stat">
            <b className="num">
              {Number(profile.bonus_balance).toFixed(0)} {config.currency}
            </b>
            <span>Бонусний рахунок</span>
          </div>
        )}
        <div className="stat">
          <b className="num">{profile.orders_count}</b>
          <span>Усього замовлень</span>
        </div>
        <div className="stat">
          <b className="num">
            {Number(profile.total_spent).toFixed(0)} {config.currency}
          </b>
          <span>Витрачено</span>
        </div>
        {config.referral_enabled && (
          <div className="stat">
            <b className="num">{profile.referrals_count}</b>
            <span>Запрошено друзів</span>
          </div>
        )}
      </div>

      {config.referral_enabled && (
        <>
      <div className="section-head">
        <h2>Запрошуйте друзів</h2>
        <p>
          Отримуйте {Number(config.referral_percent).toFixed(0)}% бонусами з кожного
          виконаного замовлення запрошеного. Бонусами можна закрити до{' '}
          {Number(config.bonus_max_percent).toFixed(0)}% вартості.
        </p>
      </div>

      {profile.referral_link ? (
        <div className="link-box">
          <code>{profile.referral_link}</code>
          <div className="link-box-actions">
            <button className="secondary" onClick={copy}>
              {copied ? 'Скопійовано' : 'Копіювати'}
            </button>
            <button className="primary" onClick={share}>Поділитись</button>
          </div>
        </div>
      ) : (
        <div className="banner warn">
          Посилання зʼявиться, коли в налаштуваннях буде вказано імʼя бота.
        </div>
      )}
        </>
      )}

      <div className="section-head">
        <h2>Історія замовлень</h2>
      </div>

      {/* Головне попередження профілю.
          У Mini App можна зайти з групи, купити й жодного разу не
          натиснути «Старт» — приватного чату з ботом тоді немає. Ззовні
          це виглядає як мовчазний магазин: ні статусів, ні реквізитів
          для оплати. Людина при цьому впевнена, що про неї забули, і йде
          в підтримку. Тому кажемо прямо й даємо кнопку, що це лікує. */}
      {profile && profile.bot_reachable === false && (
        <div className="banner warn">
          <b>Ви не отримуєте повідомлень від бота</b>
          <p>
            Статуси замовлень і реквізити для оплати приходять у чат із ботом,
            а він у вас не відкритий. Натисніть кнопку нижче й «Старт» —
            після цього все почне приходити.
          </p>
          {profile.bot_link && (
            <div className="actions">
              <button className="primary" onClick={() => openLink(profile.bot_link)}>
                Відкрити чат із ботом
              </button>
            </div>
          )}
        </div>
      )}

      {cancelError && <div className="banner warn">{cancelError}</div>}

      {orders === null ? (
        <div className="list">
          <div className="skeleton" />
        </div>
      ) : orders.length === 0 ? (
        <div className="empty">
          <h2>Історія замовлень поки порожня</h2>
          <p>Після першого оформлення покупки записи зʼявляться тут автоматично.</p>
        </div>
      ) : (
        orders.map((o) => (
          <div className="order" key={o.id}>
            <div className="order-head">
              <span className="num">№{o.id}</span>
              <span className="num">
                {Number(o.total).toFixed(0)} {config.currency}
              </span>
            </div>
            {/* Статус окремою плашкою, а не хвостом після дати: саме його
                шукають очима, коли відкривають історію. */}
            <div className="order-meta">
              <span className={`status-pill status-${o.status}`}>
                {STATUS[o.status] || o.status}
              </span>
              <span className="hint num">
                {new Date(o.created_at).toLocaleDateString('uk-UA')}
              </span>
            </div>
            <ul className="order-items">
              {o.items.map((i, idx) => (
                <li key={idx}>
                  {i.name} × {i.qty}
                </li>
              ))}
            </ul>
            {/* Кнопку показуємо лише там, де скасування ще можливе, і
                вирішує це сервер. Дві копії правила розійшлися б при
                першій зміні маршруту статусів. */}
            {o.can_cancel && (
              <button
                className="order-cancel"
                disabled={cancelling === o.id}
                onClick={() => cancel(o)}
              >
                {cancelling === o.id ? 'Скасовуємо…' : 'Скасувати замовлення'}
              </button>
            )}
          </div>
        ))
      )}

    </>
  )
}
