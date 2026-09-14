import React from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import { clientLog, registerGlobalClientLogging } from './logger'
import { getInitData, isTelegramContext, legacyHostRedirectUrl, waitForInitData } from './telegram'
import './styles.css'

async function boot() {
  const canonicalUrl = legacyHostRedirectUrl()

  if (canonicalUrl) {
    // Telegram Desktop/Android інколи спершу створює WebApp SDK на старому
    // www-host і лише потім заповнює initData. Попередня версія робила
    // location.replace синхронно — ми самі знищували той document раніше,
    // ніж Telegram устигав віддати підпис. Саме це видно в журналі як
    // legacy_redirect -> initdata_missing через ~3 секунди.
    const started = Date.now()
    let initData = getInitData()
    if (!initData && isTelegramContext()) {
      initData = await waitForInitData(4000)
    }

    const target = legacyHostRedirectUrl(initData) || canonicalUrl
    clientLog('storefront.host.legacy_redirect', {
      level: 'warning',
      message: initData
        ? 'Застарілий www host: Telegram-підпис збережено й перенесено на канонічний домен'
        : 'Застарілий www host: підпис не отримано, перехід на канонічний домен для перевірки локальної сесії',
      targetHost: new URL(target).hostname,
      authBridged: Boolean(initData),
      waitedMs: Date.now() - started,
    })
    window.location.replace(target)
    return
  }

  registerGlobalClientLogging()

  createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}

void boot()
