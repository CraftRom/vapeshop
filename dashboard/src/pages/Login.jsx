import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, apiBase, setToken } from '../api'
import { ErrorBar, Field } from '../components/ui'

export default function Login() {
  const navigate = useNavigate()
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [health, setHealth] = useState('checking')

  // Перевіряємо бекенд одразу: якщо він недоступний, це видно до спроби входу,
  // а не у вигляді незрозумілої помилки після натискання кнопки.
  useEffect(() => {
    api.health()
      .then(() => setHealth('ok'))
      .catch(() => setHealth('down'))
  }, [])

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
          {health === 'down' && (
            <div className="error-bar" role="alert">
              API недоступний за адресою <span className="mono">{apiBase}</span>.
              Перевірте, що бекенд розгорнутий на тому самому домені, або задайте
              <span className="mono"> VITE_API_URL</span>.
            </div>
          )}
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
          <button
            className="btn"
            onClick={submit}
            disabled={busy || !login || !password || health === 'down'}
          >
            {busy ? 'Входимо…' : 'Увійти'}
          </button>
        </div>
      </div>
    </div>
  )
}
