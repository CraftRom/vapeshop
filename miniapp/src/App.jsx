import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import { AgeGate, Catalog } from './screens/Catalog'
import { Cart, Checkout } from './screens/Checkout'
import { Profile } from './screens/Profile'
import {
  applyTheme, backButton, getInitData, hideMainButton, initDataSource, isTelegram,
  onThemeChange, ready,
} from './telegram'

export default function App() {
  const [config, setConfig] = useState(null)
  const [cart, setCart] = useState(null)
  const [profile, setProfile] = useState(null)
  const [tab, setTab] = useState('catalog')
  const [checkingOut, setCheckingOut] = useState(false)
  const [fatal, setFatal] = useState('')

  useEffect(() => {
    ready()
    applyTheme()
    return onThemeChange(applyTheme)
  }, [])

  const load = useCallback(() => {
    setFatal('')
    api
      .config()
      .then(setConfig)
      // Текст із бекенду не підміняємо: він називає конкретну причину
      // (порожній initData, розбіжність підпису, прострочена сесія),
      // а без неї всі 401 виглядають однаково й не діагностуються.
      .catch((err) => setFatal(err.message || 'Невідома помилка'))
  }, [])

  useEffect(load, [load])

  const refresh = useCallback(async () => {
    const [c, p] = await Promise.all([api.cart(), api.profile()])
    setCart(c)
    setProfile(p)
  }, [])

  useEffect(() => {
    if (config?.age_confirmed) refresh().catch(() => {})
  }, [config?.age_confirmed, refresh])

  // Системна кнопка «назад» веде з оформлення до кошика, а не закриває вікно
  useEffect(() => {
    if (!checkingOut) return backButton(null)
    return backButton(() => setCheckingOut(false))
  }, [checkingOut])

  useEffect(() => hideMainButton, [])

  const changeCart = useCallback(
    async (productId, delta, opts = {}) => {
      const next = opts.clear
        ? await api.clearCart()
        : await api.changeCart(productId, delta)
      setCart(next)
      api.profile().then(setProfile).catch(() => {})
      return next
    },
    [],
  )

  if (fatal) {
    return (
      <div className="empty">
        <h2>Не вдалося відкрити магазин</h2>
        <p>{fatal}</p>
        {!isTelegram && (
          <p style={{ marginTop: 10 }}>
            Застосунок відкрито поза Telegram. Скористайтесь кнопкою «Відкрити
            магазин» у чаті з ботом.
          </p>
        )}
        <div className="actions" style={{ maxWidth: 280, margin: '20px auto 0' }}>
          <button className="primary" onClick={load}>
            Спробувати ще раз
          </button>
        </div>
        {/* Технічні деталі — щоб не доводилось лізти в логи по кожен збій */}
        <details style={{ marginTop: 22, textAlign: 'left' }}>
          <summary className="hint" style={{ cursor: 'pointer' }}>
            Деталі для підтримки
          </summary>
          <pre className="hint" style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>
{`SDK Telegram: ${window.Telegram?.WebApp ? 'підключено' : 'відсутній'}
initData: ${getInitData() ? `${getInitData().length} символів` : 'порожній'}
джерело: ${initDataSource()}
поля: ${getInitData() ? [...new URLSearchParams(getInitData()).keys()].sort().join(', ') : '—'}
версія: ${window.Telegram?.WebApp?.version || '—'}
платформа: ${window.Telegram?.WebApp?.platform || '—'}
фрагмент: ${window.location.hash ? `${window.location.hash.length} символів` : 'порожній'}
походження: ${window.location.origin}`}
          </pre>
        </details>
      </div>
    )
  }

  if (!config) {
    return (
      <div className="list" style={{ paddingTop: 16 }}>
        {[0, 1, 2].map((i) => (
          <div key={i} className="skeleton" />
        ))}
      </div>
    )
  }

  if (!config.age_confirmed) {
    return <AgeGate config={config} onConfirmed={setConfig} />
  }

  const count = cart?.lines?.reduce((sum, l) => sum + l.qty, 0) || 0
  const subtotal = Number(cart?.subtotal || 0)

  if (checkingOut) {
    return (
      <div className="app" style={{ paddingBottom: 24 }}>
        <Checkout
          config={config}
          cart={cart}
          profile={profile}
          onDone={() => {
            setCheckingOut(false)
            refresh().catch(() => {})
          }}
        />
      </div>
    )
  }

  return (
    <div className="app">
      <div className="tabs" role="tablist">
        <button
          className="tab"
          role="tab"
          aria-selected={tab === 'catalog'}
          onClick={() => setTab('catalog')}
        >
          Каталог
        </button>
        <button
          className="tab"
          role="tab"
          aria-selected={tab === 'cart'}
          onClick={() => setTab('cart')}
        >
          Кошик
          {count > 0 && <span className="count num">{count}</span>}
        </button>
        <button
          className="tab"
          role="tab"
          aria-selected={tab === 'profile'}
          onClick={() => setTab('profile')}
        >
          Профіль
        </button>
      </div>

      {tab === 'catalog' && (
        <Catalog config={config} cart={cart} onCartChange={changeCart} />
      )}
      {tab === 'cart' && (
        <Cart config={config} cart={cart} onCartChange={changeCart} />
      )}
      {tab === 'profile' && <Profile config={config} profile={profile} />}

      {/* Панель тримається внизу на всіх вкладках: сума завжди перед очима */}
      <div className="bar" hidden={count === 0}>
        <div className="bar-info">
          <strong className="num">
            {subtotal.toFixed(0)} {config.currency}
          </strong>
          <span className="num">
            {count} {count === 1 ? 'товар' : count < 5 ? 'товари' : 'товарів'} у кошику
          </span>
        </div>
        <button onClick={() => setCheckingOut(true)}>Оформити</button>
      </div>

      {!isTelegram && (
        <div className="banner warn" style={{ margin: 14 }}>
          Застосунок відкрито поза Telegram — запити не пройдуть автентифікацію.
        </div>
      )}
    </div>
  )
}
