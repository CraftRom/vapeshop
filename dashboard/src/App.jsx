import { Component, Suspense, lazy, memo, useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { api, clearToken, getSession, getToken } from './api'
import { APP_VERSION } from './version'
import { Loading, ToastProvider } from './components/ui'
import { useVisiblePolling } from './components/useVisiblePolling'
import Login from './pages/Login'

// Позначка одноразового перезавантаження після оновлення панелі.
const RELOAD_MARK = 'elfar:chunk-reload'

/** Сторінка окремим чанком — із поверненням після оновлення панелі.
 *
 * Кожна сторінка вантажиться окремим файлом: головне навантаження давав
 * recharts (390 kB), тепер він тягнеться лише коли відкривають «Огляд».
 * Ціна цього рішення виявилась така. Після деплою старі файли зникають
 * із сервера, а вкладка, відкрита до нього, і далі просить їх за
 * старими іменами. Такий запит не падає видимою помилкою — Suspense
 * показує скелет і чекає вічно. Ззовні це виглядає як «сторінка не
 * грузиться взагалі»: меню живе, лічильники оновлюються, вміст не
 * приходить ніколи. А сторінки, відкриті до деплою, працюють — їхні
 * файли вже в памʼяті вкладки, і саме тому поломка здається вибірковою.
 *
 * Перезавантажуємось один раз: свіжий index.html підтягне нові імена.
 * Позначка не дає зациклитись, якщо причина інша — тоді помилка дійде
 * до запобіжника нижче, і людина побачить її, а не порожнечу.
 */
const page = (load) => lazy(() => load().then((mod) => {
  // Будь-яка вдало завантажена сторінка означає, що вкладка знову
  // збігається з сервером — знімаємо позначку, щоб наступне оновлення
  // панелі так само могло полагодити себе одним перезавантаженням.
  sessionStorage.removeItem(RELOAD_MARK)
  return mod
}).catch((err) => {
  if (sessionStorage.getItem(RELOAD_MARK)) throw err
  sessionStorage.setItem(RELOAD_MARK, '1')
  window.location.reload()
  // Сторінка вже зникає — не даємо React показати помилку по дорозі.
  return new Promise(() => {})
}))

const Overview = page(() => import('./pages/Overview'))
const Orders = page(() => import('./pages/Orders'))
const Support = page(() => import('./pages/Support'))
const Catalog = page(() => import('./pages/Catalog'))
const Customers = page(() => import('./pages/Customers'))
const Promos = page(() => import('./pages/Promos'))
const Broadcasts = page(() => import('./pages/Broadcasts'))
const Settings = page(() => import('./pages/Settings'))
const Operators = page(() => import('./pages/Operators'))
const Logs = page(() => import('./pages/Logs'))
const Backups = page(() => import('./pages/Backups'))
const Instructions = page(() => import('./pages/Instructions'))
const OrderPage = page(() => import('./pages/OrderPage'))

/** Запобіжник навколо вмісту сторінки.
 *
 * Без нього будь-яка помилка в рендері зносить усе дерево разом із
 * меню, і лишається білий екран без жодної підказки, куди дивитись.
 */
class PageBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { failed: null }
  }

  static getDerivedStateFromError(error) {
    return { failed: error }
  }

  componentDidCatch(error) {
    console.error('Сторінка не відкрилась:', error)
  }

  render() {
    if (!this.state.failed) return this.props.children

    const detail = String(this.state.failed?.message || this.state.failed)
    // Не змогли завантажити файл сторінки — це інша поломка, ніж
    // помилка в самому коді, і лікується вона інакше.
    const missing = /dynamically imported module|module script|Unexpected token/i
      .test(detail)

    return (
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Сторінка не відкрилась</h2>
        <p className="faint">
          {missing
            ? 'Не вдалось завантажити файл сторінки. Найчастіше так буває '
              + 'одразу після оновлення панелі: вкладка лишилась зі старої '
              + 'версії. Перезавантажте — якщо не допоможе, файлу немає на '
              + 'сервері, і потрібне повторне розгортання.'
            : 'Помилка під час відкриття сторінки. Текст нижче варто '
              + 'показати розробнику — за ним видно, де саме зламалось.'}
        </p>
        {/* Текст помилки на екрані, а не лише в консолі: коли панеллю
            користується менеджер, «подивіться в консолі» — це порада в
            нікуди, і причина втрачається разом із вкладкою. */}
        <p className="mono" style={{ fontSize: 12, wordBreak: 'break-word' }}>
          {detail}
        </p>
        <button className="btn" onClick={() => window.location.reload()}>
          Перезавантажити
        </button>
      </div>
    )
  }
}

const PageContent = memo(function PageContent({ children }) {
  // Бейджі sidebar оновлюються у фоні. Виносимо сторінку в memo-компонент,
  // щоб зміна двох лічильників або відкриття мобільного меню не змушували
  // React ще раз проходити велике дерево Orders/Catalog.
  return (
    <main className="main">
      <PageBoundary>
        <Suspense fallback={<Loading rows={4} />}>{children}</Suspense>
      </PageBoundary>
    </main>
  )
})

const NAV = [
  { to: '/', label: 'Огляд', end: true },
  { to: '/orders', label: 'Замовлення', badge: 'orders' },
  { to: '/support', label: 'Підтримка', badge: 'support' },
  { to: '/catalog', label: 'Каталог' },
  { to: '/customers', label: 'Клієнти' },
  { to: '/promos', label: 'Промокоди' },
  { to: '/broadcasts', label: 'Розсилки' },
  { to: '/operators', label: 'Менеджери', adminOnly: true },
  { to: '/logs', label: 'Журнал', sysadminOnly: true },
  { to: '/backups', label: 'Копії', sysadminOnly: true },
  { to: '/settings', label: 'Налаштування' },
  { to: '/instructions', label: 'Інструкції' },
]

function Shell({ children }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [badges, setBadges] = useState({ orders: 0, support: 0 })
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  // Shell монтується після входу, тому сесію достатньо прочитати один раз.
  // Раніше JSON з localStorage розбирався знову для кожного пункту меню
  // і навіть для кожного рядка в окремих сторінках.
  const session = useMemo(() => getSession(), [])
  const sysadmin = session.role === 'admin'
  const admin = sysadmin || session.role === 'shop_admin'

  // На телефоні меню розкривається поверх звичайної шапки. Після переходу
  // воно саме закривається, щоб нова сторінка одразу була перед очима.
  useEffect(() => {
    setMobileNavOpen(false)
  }, [location.pathname])

  const pollBadges = useCallback(async () => {
    // Для двох цифр у sidebar більше не рахуємо всю 30-денну статистику.
    // Один дешевий endpoint повертає лише те, що реально потрібно меню.
    const next = await api.stats.badges()
    const value = {
      orders: Number(next.orders_new || 0),
      support: Number(next.support_unread || 0),
    }
    setBadges((prev) => (
      prev.orders === value.orders && prev.support === value.support ? prev : value
    ))
  }, [])

  // 60 секунд достатньо для бейджів. При поверненні у вкладку хук сам
  // оновить їх одразу, а в background узагалі не триматиме таймер.
  useVisiblePolling(pollBadges, 60000, { immediate: true })

  const logout = () => {
    clearToken()
    navigate('/login')
  }

  return (
    <div className="shell">
      <aside className={`sidebar ${mobileNavOpen ? 'nav-open' : ''}`}>
        <div className="sidebar-head">
          <div className="brand">
            <span className="dot" />
            Панель магазину
          </div>
          <button
            className="nav-toggle"
            type="button"
            aria-expanded={mobileNavOpen}
            aria-controls="main-navigation"
            onClick={() => setMobileNavOpen((open) => !open)}
          >
            <span className="nav-toggle-lines" aria-hidden="true" />
            <span>{mobileNavOpen ? 'Закрити' : 'Меню'}</span>
          </button>
        </div>
        <nav className="nav" id="main-navigation" aria-label="Основна навігація">
          {NAV.filter((item) => {
            if (item.sysadminOnly) return sysadmin
            return !item.adminOnly || admin
          }).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
              {item.badge === 'orders' && badges.orders > 0 && <span className="badge">{badges.orders}</span>}
              {item.badge === 'support' && badges.support > 0 && (
                <span className="badge">{badges.support}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mobile-session">
          <div>
            <strong>{session.name || 'Ви'}</strong>
            <span className="faint">
              {sysadmin
                ? 'Системний адміністратор'
                : admin
                  ? 'Адміністратор'
                  : 'Менеджер'}
            </span>
          </div>
          <button className="btn ghost small" onClick={logout}>Вийти</button>
        </div>
        <div className="sidebar-foot">
          <div className="faint" style={{ marginBottom: 8, fontSize: 12.5 }}>
            {session.name || 'Ви'}
            {sysadmin
              ? ' · системний адміністратор'
              : admin
                ? ' · адміністратор'
                : ' · менеджер'}
          </div>
          <button className="btn ghost small" onClick={logout} style={{ width: '100%' }}>
            Вийти
          </button>

          {/* Версія панелі ведеться окремо від вітрини Mini App */}
          <div className="app-footer">
            v{APP_VERSION}
          </div>
        </div>
      </aside>
      <PageContent>{children}</PageContent>
    </div>
  )
}

function Protected({ children }) {
  return getToken() ? <Shell>{children}</Shell> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Protected><Overview /></Protected>} />
        <Route path="/orders" element={<Protected><Orders /></Protected>} />
        <Route path="/support" element={<Protected><Support /></Protected>} />
        <Route path="/orders/:id" element={<Protected><OrderPage /></Protected>} />
        <Route path="/catalog" element={<Protected><Catalog /></Protected>} />
        <Route path="/customers" element={<Protected><Customers /></Protected>} />
        <Route path="/promos" element={<Protected><Promos /></Protected>} />
        <Route path="/broadcasts" element={<Protected><Broadcasts /></Protected>} />
        <Route path="/settings" element={<Protected><Settings /></Protected>} />
        <Route path="/operators" element={<Protected><Operators /></Protected>} />
        <Route path="/logs" element={<Protected><Logs /></Protected>} />
        <Route path="/backups" element={<Protected><Backups /></Protected>} />
        <Route path="/instructions" element={<Protected><Instructions /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ToastProvider>
  )
}
