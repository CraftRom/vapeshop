import { useEffect, useState } from 'react'

import { api } from '../api'
import { haptic, openLink } from '../telegram'

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

  useEffect(() => {
    api.orders().then(setOrders).catch(() => setOrders([]))
  }, [])

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
        <div className="stat">
          <b className="num">
            {Number(profile.bonus_balance).toFixed(0)} {config.currency}
          </b>
          <span>Бонусний рахунок</span>
        </div>
        <div className="stat">
          <b className="num">{profile.orders_count}</b>
          <span>Замовлень</span>
        </div>
        <div className="stat">
          <b className="num">
            {Number(profile.total_spent).toFixed(0)} {config.currency}
          </b>
          <span>Витрачено</span>
        </div>
        <div className="stat">
          <b className="num">{profile.referrals_count}</b>
          <span>Запрошено друзів</span>
        </div>
      </div>

      <div className="head" style={{ paddingBottom: 6 }}>
        <h1 style={{ fontSize: 17 }}>Запрошуйте друзів</h1>
        <p>
          Отримуйте {Number(config.referral_percent).toFixed(0)}% бонусами з кожного
          виконаного замовлення запрошеного. Бонусами можна закрити до{' '}
          {Number(config.bonus_max_percent).toFixed(0)}% вартості.
        </p>
      </div>

      {profile.referral_link ? (
        <div className="link-box">
          <code>{profile.referral_link}</code>
          <button onClick={copy}>{copied ? 'Готово' : 'Копіювати'}</button>
          <button onClick={share}>Поділитись</button>
        </div>
      ) : (
        <div className="banner warn">
          Посилання зʼявиться, коли в налаштуваннях буде вказано імʼя бота.
        </div>
      )}

      <div className="head" style={{ paddingBottom: 6 }}>
        <h1 style={{ fontSize: 17 }}>Замовлення</h1>
      </div>

      {orders === null ? (
        <div className="list">
          <div className="skeleton" />
        </div>
      ) : orders.length === 0 ? (
        <div className="empty">
          <h2>Замовлень ще немає</h2>
          <p>Перше замовлення зʼявиться тут одразу після оформлення.</p>
        </div>
      ) : (
        orders.map((o) => (
          <div className="order" key={o.id}>
            <div className="order-head">
              <span>№{o.id}</span>
              <span className="num">
                {Number(o.total).toFixed(0)} {config.currency}
              </span>
            </div>
            <div className="hint">
              {new Date(o.created_at).toLocaleDateString('uk-UA')} ·{' '}
              {STATUS[o.status] || o.status}
            </div>
            <ul className="order-items">
              {o.items.map((i, idx) => (
                <li key={idx}>
                  {i.name} × {i.qty}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </>
  )
}
