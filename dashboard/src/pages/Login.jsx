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
  const [health, setHealth] = useState({ state: 'checking' })

  // Перевіряємо бекенд одразу: якщо він недоступний, це видно до спроби входу,
  // а не у вигляді незрозумілої помилки після натискання кнопки.
  useEffect(() => {
    api.health()
      .then((data) => {
        if (data.status === 'misconfigured') {
          setHealth({ state: 'misconfigured', missing: data.missing_env || [] })
        } else {
          setHealth({ state: 'ok' })
        }
      })
      .catch((err) => setHealth({ state: 'down', status: err.status }))
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
          {health.state === 'down' && (
            <div className="error-bar" role="alert">
              {health.status === 404 ? (
                <>
                  Бекенд не знайдено за адресою <span className="mono">{apiBase}</span>.
                  Функції API там не розгорнуті — перевірте, що Root Directory
                  проєкту вказує на корінь репозиторію, а не на{' '}
                  <span className="mono">dashboard</span>.
                </>
              ) : (
                <>
                  Бекенд відповів помилкою {health.status || '—'} за адресою{' '}
                  <span className="mono">{apiBase}</span>. Найчастіше це означає,
                  що не задані змінні оточення. Дивіться логи функції.
                </>
              )}
            </div>
          )}

          {health.state === 'misconfigured' && (
            <div className="error-bar" role="alert">
              Бекенд працює, але не налаштований. Не задано:{' '}
              <span className="mono">{health.missing.join(', ')}</span>.
              Додайте ці змінні оточення й передеплойте.
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
            disabled={busy || !login || !password || health.state !== 'ok'}
          >
            {busy ? 'Входимо…' : 'Увійти'}
          </button>
        </div>
      </div>
    </div>
  )
}
