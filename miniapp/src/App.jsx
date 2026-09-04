import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from './api'
import { watchFields } from './fieldGuard'
import { AgeGate, Catalog } from './screens/Catalog'
import { Cart, Checkout } from './screens/Checkout'
import { ChatList, ChatRoom } from './screens/Chat'
import { ProductPage } from './screens/ProductPage'
import { Legal, Footer } from './screens/Legal'
import { SavePicker, WishlistPage, Wishlists, isSaved } from './screens/Wishlists'
import { Profile } from './screens/Profile'
import {
  applyTheme, backButton, getInitData, hideMainButton, initDataSource, isTelegram,
  launchParamNames, notify, onThemeChange, ready, startTarget,
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
  // Відкритий список бажаного. Тримаємо номер, а не сам об'єкт: після
  // прибирання товару приходить оновлений список, і копія в стані
  // показувала б те, що вже прибрали.
  const [openListId, setOpenListId] = useState(null)
  // Екран документів: відкривається з підвалу й з оформлення
  const [legal, setLegal] = useState(null)
  const [fatal, setFatal] = useState('')

  // Кількості, які людина щойно натиснула, але сервер ще не підтвердив.
  // Показуємо суму «серверне + очікуване», тож лічильник реагує на дотик
  // одразу, а не через півсекунди.
  const [pendingQty, setPendingQty] = useState({})
  const [cartError, setCartError] = useState('')
  // Накопичені дельти й таймер відправки. У ref, а не в стані: їх читає
  // таймер, і перемальовування тут ні до чого.
  const pendingRef = useRef({})
  const flushTimer = useRef(null)

  useEffect(() => {
    ready()
    applyTheme()
    return onThemeChange(applyTheme)
  }, [])

  /* Поля введення: сторож і піднімання з-під клавіатури.
   *
   * Клас `editing`, який ховав плаваючі панелі на час набору, звідси
   * прибрано. Він міняв розмітку в мить фокуса — і саме через нього
   * форма смикалась при кожному натисканні на поле. Поломки він не
   * лікував, а зайвий рух на екрані створював.
   */
  useEffect(() => {
    const typing = (node) => Boolean(node) && (
      node.tagName === 'INPUT' || node.tagName === 'TEXTAREA'
    )

    // Клавіатура займає нижню половину екрана, а сторінка під неї не
    // прокручується сама. Затримка — на анімацію клавіатури: до неї
    // вікно ще старої висоти, і прокрутка нічого не дасть.
    const reveal = () => {
      const node = document.activeElement
      if (!typing(node)) return
      node.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
    const revealSoon = (e) => {
      if (typing(e.target)) setTimeout(reveal, 320)
    }

    document.addEventListener('focusin', revealSoon)
    window.visualViewport?.addEventListener('resize', reveal)
    const unwatch = watchFields()
    return () => {
      document.removeEventListener('focusin', revealSoon)
      window.visualViewport?.removeEventListener('resize', reveal)
      unwatch()
    }
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
    const [c, p, o, w] = await Promise.all([
      api.cart(), api.profile(), api.orders().catch(() => []),
      // Списки бажаного вантажились лише у відповідь на зміну — тобто
      // ніколи при відкритті застосунку. Через це «Збережене» в профілі
      // виглядало порожнім, поки список не створили й не видалили, а
      // вибір списку при «Відкласти» не мав що показати.
      //
      // Той самий пропуск давав 409 у журналі: назву «Список N» підбирали
      // за порожнім переліком, і вона щоразу збігалася з наявною.
      api.wishlists.list().catch(() => []),
    ])
    setCart(c)
    setProfile(p)
    setOrders(o)
    setWishlists(w || [])
  }, [])

  useEffect(() => {
    // Коментар тут раніше обіцяв, що кошик і профіль приносить bootstrap.
    // Насправді load() ходить у /config, а bootstrap не викликається
    // взагалі — усе довантажує саме refresh(). Тому умова проста: щойно
    // вік підтверджено, а даних ще немає, читаємо їх.
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
    if (openListId) return backButton(() => setOpenListId(null))
    if (chatOrder) return backButton(() => setChatOrder(null))
    return backButton(null)
  }, [checkingOut, chatOrder, openProduct, openListId, legal])

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

  /** Відправляє накопичені зміни кошика одним запитом на товар.
   *
   * Раніше кожне натискання «+» було окремим запитом, і нічого не
   * малювалось, поки він не повернеться. На телефоні з поганим звʼязком
   * три швидкі дотики виглядали як зламана кнопка: лічильник стоїть,
   * потім стрибає на три. Тепер він рухається одразу, а на сервер іде
   * одна зміна замість трьох.
   */
  const flushCart = useCallback(async () => {
    const batch = pendingRef.current
    pendingRef.current = {}
    const ids = Object.keys(batch)
    if (!ids.length) return

    try {
      let next = null
      for (const id of ids) {
        if (!batch[id]) continue
        next = await api.changeCart(Number(id), batch[id])
      }
      if (next) setCart(next)
      setCartError('')
    } catch (err) {
      // Мовчазна відмова тут найгірша: людина бачить товар у кошику,
      // якого там немає, і дізнається про це аж на оформленні.
      setCartError(err.message || 'Не вдалося змінити кошик')
      notify('error')
      try {
        setCart(await api.cart())
      } catch {
        // Якщо і перечитати не вдалося — лишаємо як є: наступна дія
        // однаково піде на сервер і принесе правду.
      }
    } finally {
      // Очікуване прибираємо лише після відповіді, інакше лічильник
      // блимне на старе значення й повернеться.
      setPendingQty((prev) => {
        const rest = { ...prev }
        for (const id of ids) delete rest[id]
        return rest
      })
    }
  }, [])

  const changeCart = useCallback(
    async (productId, delta, opts = {}) => {
      if (opts.clear) {
        try {
          setCart(await api.clearCart())
          setPendingQty({})
          pendingRef.current = {}
          setCartError('')
        } catch (err) {
          setCartError(err.message || 'Не вдалося очистити кошик')
        }
        return
      }

      setPendingQty((prev) => ({
        ...prev,
        [productId]: (prev[productId] || 0) + delta,
      }))
      pendingRef.current[productId] = (pendingRef.current[productId] || 0) + delta

      // Коротка пауза злипає серію дотиків в один запит. 350 мс —
      // помітно менше, ніж пауза між свідомими натисканнями, і достатньо,
      // щоб зловити «плюс-плюс-плюс» поспіль.
      clearTimeout(flushTimer.current)
      flushTimer.current = setTimeout(flushCart, 350)
    },
    [flushCart],
  )

  // Незбережені зміни не мають зникнути разом із екраном.
  useEffect(() => () => clearTimeout(flushTimer.current), [])

  /** Кошик, яким його бачить людина: серверний плюс те, що вже натиснуто. */
  const shownCart = useMemo(() => {
    if (!cart) return cart
    const ids = Object.keys(pendingQty).filter((id) => pendingQty[id])
    if (!ids.length) return cart

    const lines = cart.lines.map((line) => ({ ...line }))
    for (const id of ids) {
      const productId = Number(id)
      const line = lines.find((l) => l.product_id === productId)
      if (line) {
        line.qty = Math.max(0, line.qty + pendingQty[id])
      } else if (pendingQty[id] > 0) {
        // Товару в кошику ще немає — показуємо рядок наперед, інакше
        // перше натискання «У кошик» не дає жодного відгуку.
        lines.push({ product_id: productId, qty: pendingQty[id], name: '', price: 0 })
      }
    }
    // Суми лишаються серверними: знижки, промокод і бонуси рахує сервер,
    // і вигадувати їх тут означало б показати число, яке потім зміниться.
    return { ...cart, lines: lines.filter((l) => l.qty > 0) }
  }, [cart, pendingQty])

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

  // Відкритий список беремо з переліку щоразу заново: після прибирання
  // товару приходить оновлений список, і збережена копія показувала б
  // те, що вже прибрали. Якщо список тим часом видалили — просто
  // повертаємось у профіль, а не показуємо порожній екран.
  const openedList = (wishlists || []).find((w) => w.id === openListId)

  if (openListId && openedList) {
    return (
      <div className="app">
        <WishlistPage
          config={config}
          list={openedList}
          cart={shownCart}
          onChanged={onWishlistChanged}
          onOpenProduct={setOpenProduct}
          onCartChange={(product, delta) => changeCart(product.id, delta)}
        />
        <div className="screen">
          <button className="chip" onClick={() => setOpenListId(null)}>
            ← До збереженого
          </button>
        </div>
        <Footer onLegal={() => setLegal(true)} />
      </div>
    )
  }

  if (openProduct) {
    return (
      <div className="app">
        <ProductPage
          config={config}
          product={openProduct}
          cart={shownCart}
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
          cart={shownCart}
          onCartChange={changeCart}
          seed={seed}
          onOpenProduct={setOpenProduct}
          wishlists={wishlists}
          onSave={setSaving}
        />
      )}
      {/* Кошик і оформлення читають серверний стан, а не очікуваний:
          саме тут показані суми, знижки й бонуси, і розійтися вони не
          мають навіть на пів секунди. Додати новий товар звідси не можна,
          тож миттєвий відгук лічильника тут і не потрібен. */}
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
            wishlists={wishlists}
            onChanged={onWishlistChanged}
            onOpenList={(list) => setOpenListId(list.id)}
          />
        </>
      )}

      {/* Помилка кошика показується поверх усіх вкладок: натиснути «+»
          можна і в каталозі, і на сторінці товару, і в списку бажаного,
          а мовчазна відмова тут найгірша — людина побачить порожній
          кошик аж на оформленні. */}
      {cartError && (
        <div className="banner warn" style={{ margin: '0 14px 10px' }}>
          {cartError}
        </div>
      )}

      {/* Вибір списку — тут, а не всередині однієї вкладки. «Відкласти»
          натискають і в каталозі, і в «Збереженому», а вікно раніше
          малювалося лише на сторінці товару. Кнопка в каталозі виставляла
          стан, показувати який було нікому: людина тиснула, нічого не
          відбувалося, а вікно вискакувало аж коли вона відкривала товар. */}
      {saving && (
        <SavePicker
          product={saving}
          wishlists={wishlists}
          onClose={() => setSaving(null)}
          onChanged={onWishlistChanged}
        />
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
          onClick={async () => {
            // Спершу дописуємо кошик. Натиснути «+» і одразу «Оформити»
            // цілком реально, а екран оформлення читає серверний стан —
            // без цього останнє натискання просто не потрапило б до
            // замовлення.
            clearTimeout(flushTimer.current)
            await flushCart()
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
