// Stable stored role values, shared by navigation and account management.
export const ROLE_TITLES = Object.freeze({
  admin: 'Системний адміністратор',
  shop_admin: 'Адміністратор',
  operator: 'Менеджер',
})
export const isAdministrativeRole = (role) => role === 'admin' || role === 'shop_admin'
export function canAccessPage(role, pathname) {
  if (!Object.hasOwn(ROLE_TITLES, role)) return false
  try { pathname = decodeURIComponent(String(pathname)).toLowerCase() } catch { return false }
  if (/^\/(logs|backups)(\/|$)/.test(pathname)) return role === 'admin'
  if (/^\/operators(\/|$)/.test(pathname)) return isAdministrativeRole(role)
  return true
}
