import { Component, Suspense, lazy, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'

import { api, clearToken, getSession, getToken, isAdmin, isSysadmin } from './api'
import { APP_VERSION } from './version'
import { Loading, ToastProvider } from './components/ui'
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
    return (
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Сторінка не відкрилась</h2>
        <p className="faint">
          Найчастіше так буває одразу після оновлення панелі: вкладка
          лишилась зі старої версії. Перезавантажте сторінку — якщо не
          допоможе, подробиці є в консолі браузера.
        </p>
        <button className="btn" onClick={() => window.location.reload()}>
          Перезавантажити
        </button>
      </div>
    )
  }
}

const NAV = [
  { to: '/', label: 'Огляд', end: true },
  { to: '/orders', label: 'Замовлення', badge: 'orders' },
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
  const [newOrders, setNewOrders] = useState(0)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      // Не смикаємо сервер, поки вкладку не видно — на serverless це ще й гроші
      if (document.hidden) return
      try {
        const data = await api.stats.summary(30)
        if (!cancelled) setNewOrders(data.orders_new)
      } catch { /* мовчки — індикатор не критичний */ }
    }
    poll()
    const timer = setInterval(poll, 30000)
    document.addEventListener('visibilitychange', poll)
    return () => {
      cancelled = true
      clearInterval(timer)
      document.removeEventListener('visibilitychange', poll)
    }
  }, [])

  const logout = () => {
    clearToken()
    navigate('/login')
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="dot" />
          Панель магазину
        </div>
        <nav className="nav">
          {NAV.filter((item) => {
            if (item.sysadminOnly) return isSysadmin()
            return !item.adminOnly || isAdmin()
          }).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
              {item.badge === 'orders' && newOrders > 0 && <span className="badge">{newOrders}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="faint" style={{ marginBottom: 8, fontSize: 12.5 }}>
            {getSession().name || 'Ви'}
            {isSysadmin()
              ? ' · системний адміністратор'
              : isAdmin()
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
      <main className="main">
        <PageBoundary>
          <Suspense fallback={<Loading rows={4} />}>{children}</Suspense>
        </PageBoundary>
      </main>
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
