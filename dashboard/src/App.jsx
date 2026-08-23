import { Suspense, lazy, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'

import { api, clearToken, getSession, getToken, isAdmin } from './api'
import { Loading, ToastProvider } from './components/ui'
import Login from './pages/Login'

// Кожна сторінка — окремий чанк. Головне навантаження давав recharts (390 kB):
// тепер він тягнеться лише коли реально відкривають «Огляд».
const Overview = lazy(() => import('./pages/Overview'))
const Orders = lazy(() => import('./pages/Orders'))
const Catalog = lazy(() => import('./pages/Catalog'))
const Customers = lazy(() => import('./pages/Customers'))
const Promos = lazy(() => import('./pages/Promos'))
const Broadcasts = lazy(() => import('./pages/Broadcasts'))
const Settings = lazy(() => import('./pages/Settings'))
const Operators = lazy(() => import('./pages/Operators'))

const NAV = [
  { to: '/', label: 'Огляд', end: true },
  { to: '/orders', label: 'Замовлення', badge: 'orders' },
  { to: '/catalog', label: 'Каталог' },
  { to: '/customers', label: 'Клієнти' },
  { to: '/promos', label: 'Промокоди' },
  { to: '/broadcasts', label: 'Розсилки' },
  { to: '/operators', label: 'Оператори', adminOnly: true },
  { to: '/settings', label: 'Налаштування' },
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
          {NAV.filter((item) => !item.adminOnly || isAdmin()).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
              {item.badge === 'orders' && newOrders > 0 && <span className="badge">{newOrders}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="faint" style={{ marginBottom: 8, fontSize: 12.5 }}>
            {getSession().name || 'Ви'}
            {isAdmin() ? ' · адміністратор' : ' · оператор'}
          </div>
          <button className="btn ghost small" onClick={logout} style={{ width: '100%' }}>
            Вийти
          </button>
        </div>
      </aside>
      <main className="main">
        <Suspense fallback={<Loading rows={4} />}>{children}</Suspense>
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
        <Route path="/catalog" element={<Protected><Catalog /></Protected>} />
        <Route path="/customers" element={<Protected><Customers /></Protected>} />
        <Route path="/promos" element={<Protected><Promos /></Protected>} />
        <Route path="/broadcasts" element={<Protected><Broadcasts /></Protected>} />
        <Route path="/settings" element={<Protected><Settings /></Protected>} />
        <Route path="/operators" element={<Protected><Operators /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ToastProvider>
  )
}
