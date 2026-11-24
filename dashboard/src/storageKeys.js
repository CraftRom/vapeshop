// Browser storage keys and in-page event names of the dashboard (UI-029),
// in one place so components and tests cannot drift apart.
export const STORAGE = Object.freeze({
  notificationSettings: 'elfar:notification-settings',
  notificationVolume: 'elfar:notification-device-volume',
  notificationNudge: 'elfar:notification-nudge-dismissed',
  notificationLeader: 'elfar:notification-leader',
  chatDraftPrefix: 'elfar:chat-draft:v1:',
  chunkReload: 'elfar:chunk-reload',
})

export const EVENTS = Object.freeze({
  ordersChanged: 'elfar:orders:changed',
  notificationsFresh: 'elfar:notifications:fresh',
  supportRead: 'elfar:support:read',
})
