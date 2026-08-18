import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, setToken } from '../api'
import { ErrorBar, Field } from '../components/ui'

export default function Login() {
  const navigate = useNavigate()
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    setError('')
    try {
      const data = await api.login(login, password)
      setToken(data.access_token)
      navigate('/')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      <div className="card login-card">
        <h1>Панель магазину</h1>
        <p className="muted">Керування каталогом, замовленнями та розсилками</p>

        <div className="stack">
          <ErrorBar error={error} />
          <Field label="Логін">
            <input
              className="input"
              value={login}
              autoFocus
              onChange={(e) => setLogin(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
            />
          </Field>
          <Field label="Пароль">
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
            />
          </Field>
          <button className="btn" onClick={submit} disabled={busy || !login || !password}>
            {busy ? 'Входимо…' : 'Увійти'}
          </button>
        </div>
      </div>
    </div>
  )
}
