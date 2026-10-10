import { chromium } from 'playwright'
import { readFileSync, mkdirSync } from 'node:fs'
const fixture = JSON.parse(readFileSync(process.env.ANALYTICS_FIXTURE || new URL('./analytics-fixture.json', import.meta.url), 'utf8'))
const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH, args:['--no-sandbox','--disable-dev-shm-usage']})
let checks=0
function check(value,name){if(!value)throw new Error(name); checks++; console.log('PASS '+name)}
mkdirSync('qa/output',{recursive:true})
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}})
  const errors=[]; page.on('pageerror',e=>errors.push(e.message))
  const queries=[]; const spendUpdates=[]; const orderQueries=[]
  await page.route('**/api/**', async route=>{
    const url=new URL(route.request().url()); const path=url.pathname
    let data={}
    if(path.endsWith('/auth/session')) data={role:'admin',name:'QA',csrf_token:'qa'}
    else if(path.endsWith('/stats/report')) {queries.push(Object.fromEntries(url.searchParams)); data=structuredClone(fixture)}
    else if(path.endsWith('/stats/months')) data={months:['2026-10','2024-02','2024-01'],timezone:'Europe/Kyiv'}
    else if(path.endsWith('/stats/order-sources')) { orderQueries.push(Object.fromEntries(url.searchParams)); data={total:30,items:[{id:2,created_at:'2024-02-10T10:00:00Z',contact_name:'Довге ім’я тестового покупця',business_state:'sale',total:'100',revenue:'100',attribution:{source:'google',medium:'cpc',campaign:'winter',content:'creative1',term:'gift'}}]} }
    else if(path.endsWith('/stats/spend')) {
      if(route.request().method()==='PUT') {spendUpdates.push(route.request().postDataJSON());data={ok:true}} else data=[]
    } else if(path.includes('notifications')) data={items:[],unread:0}
    else if(path.includes('badges')) data={orders_new:0,support_unread:0}
    else if(path.includes('statuses')) data={statuses:[]}
    await route.fulfill({json:data})
  })
  await page.goto('http://127.0.0.1:5173/?month=2024-02&compare=month&compare_month=2024-01')
  await page.getByText('CAC · усі канали',{exact:true}).waitFor()
  check(queries[0].month==='2024-02' && queries[0].compare_month==='2024-01','historical selection survives URL reload')
  check(await page.getByText('Виручка продажів',{exact:true}).isVisible(),'financial cards render')
  check(await page.getByText('ROAS',{exact:true}).first().isVisible(),'marketing metrics render')
  check(await page.getByRole('link',{name:'#2',exact:true}).isVisible(),'each order links to its detail')
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'desktop no page overflow')
  const sourceResponse=page.waitForResponse((r)=>r.url().includes('/stats/order-sources')&&new URL(r.url()).searchParams.get('source')==='google')
  await page.getByLabel('Канал',{exact:true}).selectOption('google'); await sourceResponse
  check(orderQueries.at(-1).source==='google','order source filter reaches API')
  const nextResponse=page.waitForResponse((r)=>r.url().includes('/stats/order-sources')&&new URL(r.url()).searchParams.get('offset')==='25')
  await page.getByRole('button',{name:'Далі',exact:true}).click(); await nextResponse
  check(orderQueries.at(-1).offset==='25','orders pagination loads next page')
  await page.screenshot({path:'qa/output/analytics-desktop.png',fullPage:true})
  const monthlyResponse = page.waitForResponse((r) => r.url().includes('/stats/report') && new URL(r.url()).searchParams.get('granularity') === 'month')
  await page.getByLabel('Графік',{exact:true}).selectOption('month')
  await monthlyResponse
  await page.waitForFunction(()=>new URLSearchParams(location.search).get('granularity')==='month')
  await page.getByText('CAC · усі канали',{exact:true}).waitFor()
  check(queries.at(-1).granularity==='month','monthly granularity reaches API')
  await page.getByRole('button',{name:'Довільні дати',exact:true}).click()
  await page.getByLabel('Від',{exact:true}).fill('2024-01-01')
  const customResponse = page.waitForResponse((r) => r.url().includes('/stats/report') && new URL(r.url()).searchParams.get('date_to') === '2024-02-29')
  await page.getByLabel('До включно',{exact:true}).fill('2024-02-29')
  await customResponse
  await page.getByText('CAC · усі канали',{exact:true}).waitFor()
  check(queries.at(-1).date_to==='2024-02-29' && queries.at(-1).period==='custom','custom inclusive range reaches API')
  await page.locator('summary').filter({hasText:'Рекламні витрати'}).click()
  await page.getByLabel('Source',{exact:true}).fill('google')
  await page.getByLabel('Витрати, грн',{exact:true}).fill('125.50')
  await page.getByRole('button',{name:'Зберегти',exact:true}).click()
  await page.getByRole('status').filter({hasText:'Збережено'}).waitFor()
  check(spendUpdates.at(-1).source==='google' && spendUpdates.at(-1).amount==='125.50','spend form saves actual entered amount')
  const download=page.waitForEvent('download'); await page.getByRole('button',{name:'CSV статистики'}).click()
  check((await download).suggestedFilename()==='elfar-analytics.csv','CSV export downloadable')
  await page.setViewportSize({width:360,height:780})
  await page.getByText('CAC · усі канали',{exact:true}).waitFor()
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile no page overflow')
  const scrollable=await page.locator('.table-wrap').evaluateAll(elements=>elements.some(e=>e.scrollWidth>e.clientWidth))
  check(scrollable,'wide analytics tables scroll locally on phone')
  await page.screenshot({path:'qa/output/analytics-mobile.png',fullPage:true})
  check(!errors.length,'no React runtime errors: '+errors.join('; '))
  console.log(`BROWSER ANALYTICS: ${checks}/${checks}`)
} finally { await browser.close() }
