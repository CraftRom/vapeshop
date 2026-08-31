import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import { AgeGate, Catalog } from './screens/Catalog'
import { Cart, Checkout } from './screens/Checkout'
import { ChatList, ChatRoom } from './screens/Chat'
import { ProductPage } from './screens/ProductPage'
import { Legal, Footer } from './screens/Legal'
import { SavePicker, Wishlists, isSaved } from './screens/Wishlists'
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
  const [openProduct, setOpenProduct] = useState(null)
  // Каталог із bootstrap: перший екран малюється без додаткового запиту
  const [seed, setSeed] = useState(null)
  const [wishlists, setWishlists] = useState([])
  // Товар, для якого відкрито вибір списку
  const [saving, setSaving] = useState(null)
  // Екран документів: відкривається з підвалу й з оформлення
  const [legal, setLegal] = useState(null)
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
    if (legal) return backButton(() => setLegal(null))
    if (openProduct) return backButton(() => setOpenProduct(null))
    if (chatOrder) return backButton(() => setChatOrder(null))
    return backButton(null)
  }, [checkingOut, chatOrder, openProduct, legal])

  useEffect(() => hideMainButton, [])

  const onWishlistChanged = useCallback((updated) => {
    // Розрізняємо не «є id чи немає», а «список уже відомий чи ні».
    //
    // Раніше будь-яка відповідь з id ішла гілкою підміни, і щойно
    // створений список просто не потрапляв у перелік: map не знаходив
    // його серед наявних і мовчки лишав усе як було. Тому в «Збереженому»
    // новий список не з'являвся, у вибірці його не було, а наступна
    // спроба створити ту саму назву давала 409 — рівно те, що видно
    // в журналі дванадцять разів поспіль.
    if (updated?.id) {
      setWishlists((prev) => {
        const known = prev.some((w) => w.id === updated.id)
        return known
          ? prev.map((w) => (w.id === updated.id ? updated : w))
          : [...prev, updated]
      })
      return
    }
    // Видалення й інші зміни складу — перечитуємо повністю
    api.wishlists.list().then(setWishlists).catch(() => {})
  }, [])

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
        {saving && (
        <SavePicker
          product={saving}
          wishlists={wishlists}
          onClose={() => setSaving(null)}
          onChanged={onWishlistChanged}
        />
      )}

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
      <Footer onLegal={() => setLegal(true)} />
      </div>
    )
  }

  if (!config) {
    return (
      <div className="app">
        <div className="list" style={{ paddingTop: 16 }}>
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton" />
          ))}
        </div>
        <Footer onLegal={() => setLegal(true)} />
      </div>
    )
  }

  if (!config.age_confirmed) {
    // Футер тут обов'язковий за законом: перш ніж підтвердити вік, людина
    // має мати доступ до умов, оферти й даних продавця. Сховати їх до
    // моменту згоди означало б просити згоди наосліп.
    return (
      <div className="app">
        <AgeGate config={config} onConfirmed={setConfig} />
        <Footer onLegal={(key) => setLegal(key || true)} />
      </div>
    )
  }

  const count = cart?.lines?.reduce((sum, l) => sum + l.qty, 0) || 0
  const subtotal = Number(cart?.subtotal || 0)

  if (legal) {
    return (
      <div className="app">
        <Legal
          config={config}
          initial={legal === true ? null : legal}
          onBack={() => setLegal(null)}
        />
      </div>
    )
  }

  if (openProduct) {
    return (
      <div className="app">
        <ProductPage
          config={config}
          product={openProduct}
          cart={cart}
          onCartChange={changeCart}
          onBack={() => setOpenProduct(null)}
          saved={isSaved(wishlists, openProduct.id)}
          onSave={() => setSaving(openProduct)}
        />
        {saving && (
          <SavePicker
            product={saving}
            wishlists={wishlists}
            onClose={() => setSaving(null)}
            onChanged={onWishlistChanged}
          />
        )}
        <Footer onLegal={() => setLegal(true)} />
      </div>
    )
  }

  if (checkingOut) {
    return (
      <div className="app" style={{ paddingBottom: 24 }}>
        <Checkout
          config={config}
          cart={cart}
          profile={profile}
          onLegal={(key) => setLegal(key)}
          onDone={() => {
            setCheckingOut(false)
            refresh().catch(() => {})
          }}
        />
        <Footer onLegal={() => setLegal(true)} />
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
        <Catalog
          config={config}
          cart={cart}
          onCartChange={changeCart}
          seed={seed}
          onOpenProduct={setOpenProduct}
          wishlists={wishlists}
          onSave={setSaving}
        />
      )}
      {tab === 'cart' && (
        <Cart config={config} cart={cart} onCartChange={changeCart} />
      )}
      {tab === 'chat' && (
        chatOrder
          ? <ChatRoom config={config} order={chatOrder} onBack={() => setChatOrder(null)} />
          : <ChatList config={config} orders={orders} onOpen={setChatOrder} />
      )}
      {tab === 'profile' && (
        <>
          <Profile config={config} profile={profile} />
          {/* Збережене живе в профілі, а не окремою вкладкою: у навігації
              лишаються тільки ті розділи, куди заходять під час покупки */}
          <Wishlists
            config={config}
            wishlists={wishlists}
            cart={cart}
            onChanged={onWishlistChanged}
            onOpenProduct={setOpenProduct}
            onCartChange={(product, delta) => changeCart(product.id, delta)}
          />
        </>
      )}

      {/* Футер на всіх вкладках, а не лише в профілі.
          Посилання на документи й вікове застереження мають бути доступні
          звідусіль: людина оформлює покупку з каталогу й не мусить шукати
          умови в іншому розділі. */}
      <Footer onLegal={() => setLegal(true)} />

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
