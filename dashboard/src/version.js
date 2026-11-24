/** Версія панелі керування.
 *
 * Нумерується окремо від вітрини: це різні застосунки з різним циклом
 * випусків, і спільний номер плутав би — правка в панелі не означає
 * змін для покупця.
 *
 * Формат: МАЖОРНА.МІНОРНА.ВИПРАВЛЕННЯ
 *   мажорна     — несумісні зміни, потрібна міграція або дії адміністратора
 *   мінорна     — нова можливість
 *   виправлення — лагодження без нових можливостей
 */
export const APP_VERSION = '1.83.0'
// A13: content digest of this bundle, injected by the Vite release plugin.
// Test bundles built without Vite fall back to a visible "dev" marker.
export const RELEASE_ID = typeof __APP_RELEASE__ !== 'undefined' ? __APP_RELEASE__ : 'dashboard+dev'
