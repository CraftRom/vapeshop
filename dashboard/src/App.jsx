import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'

import { api, clearToken, getToken } from './api'
import { ToastProvider } from './components/ui'
import Broadcasts from './pages/Broadcasts'
import Catalog from './pages/Catalog'
import Customers from './pages/Customers'
import Login from './pages/Login'
import Orders from './pages/Orders'
import Overview from './pages/Overview'
import Promos from './pages/Promos'

const NAV = [
  { to: '/', label: 'Огляд', end: true },
  { to: '/orders', label: 'Замовлення', badge: 'orders' },
  { to: '/catalog', label: 'Каталог' },
  { to: '/customers', label: 'Клієнти' },
  { to: '/promos', label: 'Промокоди' },
  { to: '/broadcasts', label: 'Розсилки' },
]

function Shell({ children }) {
  const navigate = useNavigate()
  const [newOrders, setNewOrders] = useState(0)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const data = await api.stats.summary(30)
        if (!cancelled) setNewOrders(data.orders_new)
      } catch { /* мовчки — індикатор не критичний */ }
    }
    poll()
    const timer = setInterval(poll, 30000)
    return () => { cancelled = true; clearInterval(timer) }
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
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
              {item.badge === 'orders' && newOrders > 0 && <span className="badge">{newOrders}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button className="btn ghost small" onClick={logout} style={{ width: '100%' }}>
            Вийти
          </button>
        </div>
      </aside>
      <main className="main">{children}</main>
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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ToastProvider>
  )
}
