/** Regression: збій довідника Нової пошти не залишає покупця без відділення.
 * У журналі вітрини 502/503 на /delivery/warehouses приходили пачками:
 * сервер ставив довідник на паузу, а вітрина повторювала запит у цю паузу й
 * показувала помилку замість ручного введення.
 * Запуск: cd miniapp && node tests/checkout-directory-outage.mjs
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const checkout = readFileSync('src/screens/Checkout.jsx', 'utf8')
const api = readFileSync('src/api.js', 'utf8')
const router = readFileSync('../backend/api/routers/shop.py', 'utf8')

let passed = 0
function check(name, condition) {
  assert.ok(condition, name)
  console.log(`PASS ${name}`)
  passed += 1
}

function extract(source, signature) {
  const start = source.indexOf(signature)
  assert.ok(start >= 0, `немає ${signature}`)
  let depth = 0
  for (let i = source.indexOf('{', start); i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1)
  }
  throw new Error(`не закрито ${signature}`)
}

// eslint-disable-next-line no-new-func
const directoryUnavailable = new Function(`${extract(checkout, 'function directoryUnavailable(')}; return directoryUnavailable`)()
check('503 (not configured or paused) switches to manual entry', directoryUnavailable({ status: 503 }))
check('504 gateway timeout switches to manual entry', directoryUnavailable({ status: 504 }))
check('client timeout switches to manual entry', directoryUnavailable({ name: 'TimeoutError' }))
check('502 rejection keeps directory (another query may work)', !directoryUnavailable({ status: 502 }))
check('400 is not an outage', !directoryUnavailable({ status: 400 }))

const retryAfterSeconds = new Function(`${extract(api, 'function retryAfterSeconds(')}; return retryAfterSeconds`)()
const res = (value) => ({ headers: { get: (name) => (name === 'Retry-After' ? value : null) } })
check('Retry-After parsed', retryAfterSeconds(res('20')) === 20)
check('missing Retry-After is 0', retryAfterSeconds(res(null)) === 0)
check('garbage Retry-After is 0', retryAfterSeconds(res('soon')) === 0)

check('GET is not retried into a known pause', api.includes("!(res.status === 503 && retryAfter > 2)"))
check('error carries retryAfter', api.includes('error.retryAfter = retryAfter'))
check('both directory searches use the outage rule',
  (checkout.match(/if \(directoryUnavailable\(err\)\) setDirectoryDown\(true\)/g) || []).length === 2)
check('manual-entry hint still shown when directory is down',
  checkout.includes('Довідник зараз недоступний. Введіть населений пункт вручну.'))
check('backend maps provider outage to 503 with Retry-After',
  router.includes('isinstance(exc, np.NovaPoshtaUnavailable)') && router.includes('"Retry-After"'))
check('all directory routes use the shared mapping',
  (router.match(/raise _directory_error\(exc\) from exc/g) || []).length === 3)
console.log(`CHECKOUT DIRECTORY OUTAGE: ${passed}/${passed}`)
