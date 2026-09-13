import React from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import { clientLog, registerGlobalClientLogging } from './logger'
import { legacyHostRedirectUrl } from './telegram'
import './styles.css'

const canonicalUrl = legacyHostRedirectUrl()

if (canonicalUrl) {
  // Старі Named Mini App / закешовані Telegram-кнопки ще можуть вести на
  // www. Не запускаємо React на неправильному origin: там інше сховище й
  // немає кешованого initData. keepalive дає журналу шанс зафіксувати
  // причину перед переходом.
  clientLog('storefront.host.legacy_redirect', {
    level: 'warning',
    message: 'Застарілий www host перенаправлено на канонічний домен',
    targetHost: new URL(canonicalUrl).hostname,
  })
  window.location.replace(canonicalUrl)
} else {
  registerGlobalClientLogging()

  createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}
