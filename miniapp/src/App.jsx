import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, consumeOrderEvents } from './api'
import { clientLog } from './logger'
import { AgeGate, Catalog } from './screens/Catalog'
import { Cart, Checkout } from './screens/Checkout'
import { ChatList, ChatRoom } from './screens/Chat'
import { ProductPage } from './screens/ProductPage'
import { Legal, Footer } from './screens/Legal'
import { SavePicker, WishlistPage, Wishlists, isSaved } from './screens/Wishlists'
import { Profile } from './screens/Profile'
import {
  applyTheme, backButton, getInitData, hideMainButton, initDataSource, isTelegramContext,
  launchParamNames, notify, onThemeChange, ready, startTarget, waitForInitData,
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
  // Серіалізує flush кошика. Якщо debounce уже почав POST, кнопка
  // «Оформити» має дочекатися саме його, а не побачити порожній pendingRef
  // і відкрити checkout зі старим серверним кошиком.
  const flushInFlight = useRef(Promise.resolve())

  useEffect(() => {
    ready()
    applyTheme()
    return onThemeChange(applyTheme)
  }, [])

  /* Клавіатура займає нижню половину екрана, а сторінка під неї не
   * прокручується сама. Піднімаємо активне поле у видиму частину із
   * затримкою на анімацію клавіатури: до неї вікно ще старої висоти.
   */
  useEffect(() => {
    const typing = (node) => Boolean(node) && (
      node.tagName === 'INPUT' || node.tagName === 'TEXTAREA'
    )
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
    return () => {
      document.removeEventListener('focusin', revealSoon)
      window.visualViewport?.removeEventListener('resize', reveal)
    }
  }, [])

  const load = useCallback(async () => {
    setFatal('')
    // Частина Telegram WebView спершу створює window.Telegram.WebApp і лише
    // через кілька сотень мілісекунд заповнює initData. Раніше ми перевіряли
    // його синхронно й показували хибну помилку. Тепер коротко чекаємо.
    const init = getInitData() || await waitForInitData(2500)
    if (init && initDataSource() === 'кеш пристрою') {
      clientLog('storefront.telegram.initdata_recovered', {
        message: 'Telegram initData відновлено з кешу канонічного origin',
        once: 'initdata-recovered',
      })
    }
    if (!init) {
      clientLog('storefront.telegram.initdata_missing', {
        level: 'warning',
        message: 'Telegram initData відсутній після очікування',
        once: 'initdata-missing',
      })
      setFatal(
        'Магазин відкрито без авторизації Telegram. Закрийте це вікно й '
        + 'відкрийте магазин кнопкою в особистому чаті з ботом. Якщо помилка '
        + 'повторюється саме в Telegram — повідомте підтримку: діагностику вже записано.',
      )
      return
    }

    api.config()
      .then((value) => {
        setConfig(value)
        clientLog('storefront.open.ok', {
          message: 'Вітрина успішно отримала конфігурацію',
          once: 'open-ok',
        })
      })
      .catch((err) => {
        // Повтори безпечних GET централізовані в api.js. Тут не дублюємо
        // таймери й не створюємо кілька паралельних ланцюжків завантаження.
        clientLog('storefront.open.failed', {
          level: 'error', message: err?.message || 'Невідома помилка',
          status: err?.status || null,
        })
        setFatal(err.message || 'Невідома помилка')
      })
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

  // Тихий read-side refresh вітрини. Чат має свій швидший delta-poll,
  // а тут синхронізуємо статуси замовлень, профіль і кошик між вкладками/
  // пристроями без spinner-ів та перезавантаження екрана.
  const backgroundSyncRef = useRef(false)
  useEffect(() => {
    if (!config?.age_confirmed) return undefined
    let stopped = false
    let cycle = 0
    let timer = null

    const visibleAndOnline = () => !document.hidden && navigator.onLine !== false
    const clearTimer = () => {
      if (timer !== null) {
        clearTimeout(timer)
        timer = null
      }
    }
    const schedule = (delay = 20000) => {
      clearTimer()
      if (!stopped && visibleAndOnline()) timer = window.setTimeout(sync, delay)
    }

    const sync = async () => {
      if (stopped || !visibleAndOnline() || backgroundSyncRef.current) return
      backgroundSyncRef.current = true
      cycle += 1
      try {
        const jobs = [api.orders(), api.profile()]
        // Кошик не перечитуємо поверх ще не відправлених optimistic +/- .
        const canRefreshCart = Object.keys(pendingRef.current || {}).length === 0
        if (canRefreshCart && cycle % 2 === 0) jobs.push(api.cart())
        else jobs.push(Promise.resolve(null))
        if (cycle % 4 === 0) jobs.push(api.config())
        else jobs.push(Promise.resolve(null))

        const [ordersResult, profileResult, cartResult, configResult] = await Promise.allSettled(jobs)
        if (stopped) return
        if (ordersResult.status === 'fulfilled') setOrders(ordersResult.value || [])
        if (profileResult.status === 'fulfilled') setProfile(profileResult.value)
        if (cartResult.status === 'fulfilled' && cartResult.value) setCart(cartResult.value)
        if (configResult.status === 'fulfilled' && configResult.value) setConfig(configResult.value)
      } finally {
        backgroundSyncRef.current = false
        schedule()
      }
    }

    const wake = () => {
      clearTimer()
      if (visibleAndOnline()) sync()
    }
    schedule()
    document.addEventListener('visibilitychange', wake)
    window.addEventListener('focus', wake)
    window.addEventListener('online', wake)
    return () => {
      stopped = true
      clearTimer()
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('focus', wake)
      window.removeEventListener('online', wake)
    }
  }, [config?.age_confirmed])

  // Primary realtime path for customer-visible order state. Redis/SSE only
  // invalidates the read-model; actual data is always re-read through the
  // signed Mini App API. The 20s DB-only background sync above remains recovery.
  const liveRefreshRef = useRef(false)
  useEffect(() => {
    if (!config?.age_confirmed) return undefined
    let stopped = false
    let controller = null
    let retryTimer = null
    let refreshTimer = null
    let retryMs = 1000

    const refreshOrderState = async () => {
      if (stopped || liveRefreshRef.current || document.hidden || navigator.onLine === false) return
      liveRefreshRef.current = true
      try {
        const [ordersResult, profileResult] = await Promise.allSettled([api.orders(), api.profile()])
        if (stopped) return
        if (ordersResult.status === 'fulfilled') setOrders(ordersResult.value || [])
        if (profileResult.status === 'fulfilled') setProfile(profileResult.value)
      } finally {
        liveRefreshRef.current = false
      }
    }

    const stopConnection = () => {
      controller?.abort()
      controller = null
      if (retryTimer) clearTimeout(retryTimer)
      retryTimer = null
    }

    const scheduleReconnect = () => {
      if (stopped || document.hidden || navigator.onLine === false) return
      if (retryTimer) clearTimeout(retryTimer)
      retryTimer = setTimeout(connect, retryMs)
      retryMs = Math.min(15000, retryMs * 2)
    }

    const onOrder = () => {
      if (refreshTimer) clearTimeout(refreshTimer)
      refreshTimer = setTimeout(() => refreshOrderState().catch(() => {}), 80)
    }

    const connect = async () => {
      if (stopped || document.hidden || navigator.onLine === false) return
      stopConnection()
      controller = new AbortController()
      try {
        await consumeOrderEvents(onOrder, controller.signal)
        retryMs = 1000
      } catch (err) {
        if (err?.name === 'AbortError' || stopped) return
        clientLog('storefront.orders.realtime_disconnected', {
          level: 'warning', message: err?.message || 'Realtime connection failed',
          status: err?.status || null,
        })
      }
      scheduleReconnect()
    }

    const wake = () => {
      if (document.hidden || navigator.onLine === false) stopConnection()
      else { retryMs = 1000; connect(); refreshOrderState().catch(() => {}) }
    }

    document.addEventListener('visibilitychange', wake)
    window.addEventListener('online', wake)
    window.addEventListener('offline', wake)
    connect()
    return () => {
      stopped = true
      stopConnection()
      if (refreshTimer) clearTimeout(refreshTimer)
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('online', wake)
      window.removeEventListener('offline', wake)
    }
  }, [config?.age_confirmed])

  // Open chat gets the same fresh object as the list/profile. Otherwise a
  // status changed by CRM would update the list but leave the open room with
  // the old badge until the user navigated back.
  useEffect(() => {
    if (!chatOrder) return
    const fresh = orders.find((order) => order.id === chatOrder.id)
    if (fresh && fresh !== chatOrder) setChatOrder(fresh)
  }, [orders, chatOrder?.id])

  // Кнопка «Відкрити чат» у боті веде одразу на потрібну розмову.
  //
  // Спрацьовує рівно один раз за запуск. Раніше умови не було, і вихід
  // із чату не працював зовсім: людина натискала «Назад», chatOrder
  // ставав порожнім, ефект бачив це як «розмову ще не відкрито» і
  // відкривав її знову. Ззовні кнопка просто не діяла, і Telegram
  // доводилось закривати цілком.
  const deepLinkUsed = useRef(false)
  useEffect(() => {
    if (deepLinkUsed.current || orders.length === 0) return
    const target = startTarget()
    if (!target) return
    const found = orders.find((o) => o.id === target.orderId)
    if (!found) return
    deepLinkUsed.current = true
    setTab('chat')
    setChatOrder(found)
  }, [orders])

  // Системна кнопка «назад» веде з оформлення до кошика, а не закриває вікно
  useEffect(() => {
    // Найверхніший overlay/екран закривається першим. Legal може бути
    // відкритий поверх checkout, SavePicker — поверх товару: старий порядок
    // закривав батьківський екран і кнопка «Назад» виглядала зламаною.
    if (legal) return backButton(() => setLegal(null))
    if (saving) return backButton(() => setSaving(null))
    if (checkingOut) return backButton(() => setCheckingOut(false))
    if (openProduct) return backButton(() => setOpenProduct(null))
    if (openListId) return backButton(() => setOpenListId(null))
    if (chatOrder) return backButton(() => setChatOrder(null))
    return backButton(null)
  }, [checkingOut, chatOrder, openProduct, openListId, legal, saving])

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
    const run = async () => {
      const batch = pendingRef.current
      pendingRef.current = {}
      const ids = Object.keys(batch)
      if (!ids.length) return cart

      try {
        let next = null
        for (const id of ids) {
          if (!batch[id]) continue
          next = await api.changeCart(Number(id), batch[id])
        }
        if (next) setCart(next)
        setCartError('')
        return next
      } catch (err) {
        setCartError(err.message || 'Не вдалося змінити кошик')
        notify('error')
        try {
          const fresh = await api.cart()
          setCart(fresh)
          return fresh
        } catch {
          return null
        }
      } finally {
        setPendingQty((prev) => {
          const rest = { ...prev }
          for (const id of ids) delete rest[id]
          return rest
        })
      }
    }

    // Якщо попередній debounce уже в мережі, наступний batch піде після
    // нього. Це також робить await flushCart() справжнім барʼєром перед
    // checkout, а не лише читанням поточного pendingRef.
    const queued = flushInFlight.current.catch(() => null).then(run)
    flushInFlight.current = queued
    return queued
  }, [cart])

  const changeCart = useCallback(
    async (productId, delta, opts = {}) => {
      if (opts.clear) {
        // Очищення теж стає в ту саму чергу, що й +/- . Інакше сценарій
        // «натиснув + і відразу очистити» запускав POST /cart та DELETE
        // паралельно: повільний POST міг завершитись останнім і повернути
        // вже очищений товар назад у кошик.
        clearTimeout(flushTimer.current)
        pendingRef.current = {}
        setPendingQty({})
        const clearRun = flushInFlight.current.catch(() => null).then(() => api.clearCart())
        flushInFlight.current = clearRun
        try {
          setCart(await clearRun)
          setCartError('')
        } catch (err) {
          setCartError(err.message || 'Не вдалося очистити кошик')
          try { setCart(await api.cart()) } catch { /* наступна дія перечитає */ }
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

        {!isTelegramContext() && (
          <p>
            Застосунок відкрито поза Telegram. Скористайтесь кнопкою «Відкрити
            магазин» у чаті з ботом.
          </p>
        )}
        <div className="actions">
          <button className="primary" onClick={load}>
            Спробувати ще раз
          </button>
          {window.Telegram?.WebApp && !getInitData() && (
            <button onClick={() => window.Telegram.WebApp.close?.()}>
              Закрити й повернутися в Telegram
            </button>
          )}
        </div>
        {/* Технічні деталі — щоб не доводилось лізти в логи по кожен збій */}
        <details className="support-details">
          <summary className="hint">
            Деталі для підтримки
          </summary>
          <pre className="hint num">
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
        <div className="list list-loading">
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

  if (openListId && openedList) {
    return (
      <div className="app">
        {/* Назад — над списком, як на сторінці товару. Під списком кнопку
            треба було шукати, догортаючи до кінця. */}
        <div className="page-back">
          <button className="back" onClick={() => setOpenListId(null)}>
            До збереженого
          </button>
        </div>
        <WishlistPage
          config={config}
          list={openedList}
          cart={shownCart}
          onChanged={onWishlistChanged}
          onOpenProduct={setOpenProduct}
          onCartChange={(product, delta) => changeCart(product.id, delta)}
        />
        <Footer onLegal={() => setLegal(true)} />
      </div>
    )
  }

  if (checkingOut) {
    return (
      <div className="app app-form">
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
      {/* Шапка в один рядок: назва магазину й вікова позначка. Раніше тут
          були два рядки й окремий блок-заставка в каталозі — разом вони
          з'їдали пів екрана, і до першого товару доводилось гортати. */}
      <header className="store-head">
        <strong className="store-name">{config.shop_name || 'Магазин'}</strong>
        <span className="store-age" title="Лише для повнолітніх">
          {config.min_age ?? 18}+
        </span>
      </header>

      <div className="tabs" role="tablist" aria-label="Розділи магазину">
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
          <Profile config={config} profile={profile} orders={orders} onOrdersChange={setOrders} />
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
        <div className="banner warn">
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

      {!isTelegramContext() && (
        <div className="banner warn">
          Застосунок відкрито поза Telegram — запити не пройдуть автентифікацію.
        </div>
      )}
    </div>
  )
}
