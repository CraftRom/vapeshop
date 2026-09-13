import fs from 'node:fs'

const logger = fs.readFileSync('src/logger.js', 'utf8')
const api = fs.readFileSync('src/api.js', 'utf8')
const app = fs.readFileSync('src/App.jsx', 'utf8')
const tg = fs.readFileSync('src/telegram.js', 'utf8')
const photo = fs.readFileSync('src/photo.jsx', 'utf8')
const version = fs.readFileSync('src/version.js', 'utf8')
let failed = 0
function check(ok, name) { console.log(`${ok ? 'OK' : 'FAIL'} ${name}`); if (!ok) failed++ }

check(version.includes("2.8.1"), 'вітрина 2.8.1')
check(logger.includes("/api/shop/client-log"), 'є endpoint клієнтського журналу')
check(logger.includes('MAX_PER_SESSION'), 'є межа записів на сесію')
check(!logger.includes('init_data: init,'), 'raw initData не відправляється')
check(logger.includes('unhandledrejection') && logger.includes("window.addEventListener('error'"), 'глобальні JS помилки логуються')
check(api.includes('AbortController') && api.includes('12000'), 'API має мережевий timeout')
check(api.includes('storefront.api.network_error') && api.includes('storefront.api.http_error'), 'мережеві та HTTP помилки розділені')
check(app.includes('waitForInitData(2500)'), 'Telegram initData чекаємо перед fatal')
check(app.includes('storefront.telegram.initdata_missing'), 'відсутність initData потрапляє в журнал')
check(tg.includes('isTelegramContext()'), 'контекст Telegram визначається динамічно')
check(logger.includes('safePath('), 'битий filename у window.error не валить сам logger')
check(photo.includes('!product.has_photo'), 'товари без фото не роблять зайвий GET → 404')
check(photo.includes('storefront.photo.failed'), 'реальні збої фото потрапляють у журнал')

if (failed) process.exit(1)

check(tg.includes('legacyHostRedirectUrl') && tg.includes("['www.elfar.pp.ua', 'elfar.pp.ua']"), 'www self-heal зберігає поточний URL')
check(tg.includes('fromSearch()') && tg.includes("return fromParamString(window.location.search)"), 'initData читається також із query')
check(app.includes('storefront.telegram.initdata_recovered'), 'відновлення initData з кешу логуються')
