self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const href = event.notification?.data?.href || '/'
  event.waitUntil((async () => {
    const all = await clients.matchAll({ type: 'window', includeUncontrolled: true })
    const target = new URL(href, self.location.origin).href

    // Service worker has root scope because the admin panel uses several root
    // routes. Never reuse/navigate the customer Mini App window (/app): a
    // manager notification must not replace an open storefront session.
    const panelWindows = all.filter((client) => {
      try {
        return !new URL(client.url).pathname.startsWith('/app')
      } catch {
        return false
      }
    })

    for (const client of panelWindows) {
      if ('focus' in client) {
        if ('navigate' in client) await client.navigate(target)
        await client.focus()
        return
      }
    }
    if (clients.openWindow) await clients.openWindow(target)
  })())
})
