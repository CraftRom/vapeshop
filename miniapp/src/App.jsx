import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import { AgeGate, Catalog } from './screens/Catalog'
import { Cart, Checkout } from './screens/Checkout'
import { ChatList, ChatRoom } from './screens/Chat'
import { Profile } from './screens/Profile'
import {
  applyTheme, backButton, getInitData, hideMainButton, initDataSource, isTelegram,
  launchParamNames, onThemeChange, ready, startTarget,
} from './telegram'

export default function App() {
  const [config, setConfig] = useState(null)
  const [cart, setCart] = useState(null)
  const [profile, setProfile] = useState(null)
  const [tab, setTab] = useState('catalog')
  const [checkingOut, setCheckingOut] = useState(false)
  const [orders, setOrders] = useState([])
  // Відкрите замовлення в чаті. Кнопка з бота веде сюди напряму.
  const [chatOrder, setChatOrder] = useState(null)
  // Каталог із bootstrap: перший екран малюється без додаткового запиту
  const [seed, setSeed] = useState(null)
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
    const [c, p, o] = await Promise.all([
      api.cart(), api.profile(), api.orders().catch(() => []),
    ])
    setCart(c)
    setProfile(p)
    setOrders(o)
  }, [])

  useEffect(() => {
    // bootstrap уже приніс кошик і профіль; довантажуємо лише тоді,
    // коли вік підтвердили вже в застосунку і даних ще немає
    if (config?.age_confirmed && !cart) refresh().catch(() => {})
  }, [config?.age_confirmed, cart, refresh])

  // Кнопка «Відкрити чат» у боті веде одразу на потрібну розмову
  useEffect(() => {
    const target = startTarget()
    if (!target || chatOrder || orders.length === 0) return
    const found = orders.find((o) => o.id === target.orderId)
    if (found) {
      setTab('chat')
      setChatOrder(found)
    }
  }, [orders, chatOrder])

  // Системна кнопка «назад» веде з оформлення до кошика, а не закриває вікно
  useEffect(() => {
    if (checkingOut) return backButton(() => setCheckingOut(false))
    if (chatOrder) return backButton(() => setChatOrder(null))
    return backButton(null)
  }, [checkingOut, chatOrder])

  useEffect(() => hideMainButton, [])

  const changeCart = useCallback(
    async (productId, delta, opts = {}) => {
      const next = opts.clear
        ? await api.clearCart()
        : await api.changeCart(productId, delta)
      setCart(next)
      // Профіль тут не перечитуємо: у ньому змінюється лише доступний
      // ліміт бонусів, а він потрібен аж на екрані оформлення
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
параметри запуску: ${launchParamNames().join(', ') || '—'}
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
          aria-selected={tab === 'chat'}
          onClick={() => setTab('chat')}
        >
          Чат
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
        <Catalog config={config} cart={cart} onCartChange={changeCart} seed={seed} />
      )}
      {tab === 'cart' && (
        <Cart config={config} cart={cart} onCartChange={changeCart} />
      )}
      {tab === 'chat' && (
        chatOrder
          ? <ChatRoom config={config} order={chatOrder} onBack={() => setChatOrder(null)} />
          : <ChatList config={config} orders={orders} onOpen={setChatOrder} />
      )}
      {tab === 'profile' && <Profile config={config} profile={profile} />}

      {/* Панель тримається внизу на всіх вкладках: сума завжди перед очима */}
      {/* У чаті панель кошика перекрила б поле вводу */}
      <div className="bar" hidden={count === 0 || tab === 'chat'}>
        <div className="bar-info">
          <strong className="num">
            {subtotal.toFixed(0)} {config.currency}
          </strong>
          <span className="num">
            {count} {count === 1 ? 'товар' : count < 5 ? 'товари' : 'товарів'} у кошику
          </span>
        </div>
        <button
          onClick={() => {
            // Ліміт бонусів міг змінитися, поки набирали кошик
            api.profile().then(setProfile).catch(() => {})
            setCheckingOut(true)
          }}
        >
          Оформити
        </button>
      </div>

      {!isTelegram && (
        <div className="banner warn" style={{ margin: 14 }}>
          Застосунок відкрито поза Telegram — запити не пройдуть автентифікацію.
        </div>
      )}
    </div>
  )
}
