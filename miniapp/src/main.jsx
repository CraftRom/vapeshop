import React from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import { clientLog, registerGlobalClientLogging } from './logger'
import { getInitData, isTelegramContext, legacyHostRedirectUrl, waitForInitData } from './telegram'
import './styles.css'

function StorefrontPreparing() {
  return (
    <main className="prepare-screen" role="status" aria-live="polite">
      <div className="prepare-glow prepare-glow-one" aria-hidden="true" />
      <div className="prepare-glow prepare-glow-two" aria-hidden="true" />

      <section className="prepare-card">
        <div className="prepare-workshop" aria-hidden="true">
          <span className="prepare-gear gear-a">✦</span>
          <span className="prepare-gear gear-b">✦</span>
          <span className="prepare-hammer">⌁</span>
        </div>

        <div className="prepare-kicker">ELFAR · MINI APP</div>
        <h1>Почекай — гноми налаштовують вітрину</h1>
        <p>
          Перевіряємо безпечний вхід через Telegram, переносимо сесію та
          готуємо каталог. Зазвичай це займає лише кілька секунд.
        </p>

        <div className="prepare-progress" aria-hidden="true">
          <span />
        </div>

        <div className="prepare-steps" aria-hidden="true">
          <span><i /> Зʼєднання</span>
          <span><i /> Авторизація</span>
          <span><i /> Вітрина</span>
        </div>
      </section>
    </main>
  )
}

async function boot() {
  const root = createRoot(document.getElementById('root'))
  const canonicalUrl = legacyHostRedirectUrl()

  if (canonicalUrl) {
    // До чотирьох секунд ми навмисно чекаємо Telegram initData. Раніше
    // цей проміжок був просто порожнім екраном і виглядав як зависання.
    // Тепер пояснюємо людині, що саме відбувається, поки переносимо
    // авторизовану сесію зі старого host на канонічний.
    root.render(<StorefrontPreparing />)
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

  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}

void boot()
