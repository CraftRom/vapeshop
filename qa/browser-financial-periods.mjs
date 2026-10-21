import { chromium } from 'playwright'
import { readFileSync } from 'node:fs'
const fixture = JSON.parse(readFileSync(new URL('./analytics-fixture.json', import.meta.url), 'utf8'))
const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH, args:['--no-sandbox','--disable-dev-shm-usage']})
let checks=0
const check=(ok,label)=>{if(!ok)throw new Error(label);checks++;console.log('PASS '+label)}
try {
 for (const width of [320,390,1280]) {
  const page=await browser.newPage({viewport:{width,height:900},acceptDownloads:true})
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  const saved={...structuredClone(fixture),previous:null,changes:{},snapshot:{month:'2024-02',timezone:'Europe/Kyiv',closed_at:'2024-04-01T09:00:00+00:00',closed_by:'qa-admin',checksum:'abc123',schema_version:1}}
  saved.analytics.metrics.sales='199.90';saved.window.partial=false;saved.window.previous_from=null;saved.window.previous_to=null
  const rows=[saved.snapshot];let posts=0,listFail=true,detailFail=false,detailReads=0,hold=null,heldReady=null
  let captureHold=false
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url()),path=url.pathname,method=route.request().method()
   let data={}
   if(path.endsWith('/auth/session'))data={role:'admin',name:'QA',csrf_token:'qa'}
   else if(path.endsWith('/stats/closed-periods')) {
    if(method==='POST') {
     posts++;const body=route.request().postDataJSON();check(body.month==='2024-03',`${width}: close uses confirmed month only`)
     check(route.request().headers()['x-csrf-token']==='qa',`${width}: close uses session CSRF transport`)
     if(!rows.some(r=>r.month===body.month))rows.push({...saved.snapshot,month:body.month})
     if(posts===1)return route.fulfill({status:503,json:{detail:'Відповідь втрачено. Перевірте збереження.'}})
     data={...saved,snapshot:rows.find(r=>r.month===body.month)}
    } else {
     if(listFail){return route.fulfill({status:503,json:{detail:'Список тимчасово недоступний'}})}
     data={items:rows}
    }
   } else if(path.includes('/stats/closed-periods/')) {
    detailReads++
    if(detailFail){detailFail=false;return route.fulfill({status:404,json:{detail:'Збережений звіт відсутній'}})}
    data={...structuredClone(saved),snapshot:rows.find(r=>r.month===path.split('/').at(-1))||saved.snapshot}
    if(captureHold){captureHold=false;heldReady?.();await new Promise(resolve=>{hold=resolve})}
   } else if(path.endsWith('/stats/report'))data=structuredClone(fixture)
   else if(path.endsWith('/stats/months'))data={months:['2026-10','2024-03','2024-02'],timezone:'Europe/Kyiv'}
   else if(path.endsWith('/stats/spend'))data=[]
   else if(path.endsWith('/stats/order-sources'))data={items:[],total:0}
   else if(path.includes('notifications'))data={items:[],unread:0}
   else if(path.includes('badges'))data={orders_new:0,support_unread:0}
   else if(path.includes('statuses'))data={statuses:[]}
   await route.fulfill({json:data})
  })
  await page.goto('http://127.0.0.1:5173/')
  await page.getByRole('button',{name:'Оновити список звітів',exact:true}).waitFor()
  check(await page.getByText('Список тимчасово недоступний',{exact:true}).isVisible(),`${width}: list failure is explicit`)
  listFail=false;await page.getByRole('button',{name:'Оновити список звітів',exact:true}).click()
  await page.waitForFunction(()=>document.querySelector('[aria-label="Перегляд звіту"]').options.length===2)
  await page.getByLabel('Місяць для фіксації',{exact:true}).fill('2024-03')
  await page.getByRole('button',{name:'Зафіксувати місяць',exact:true}).click()
  await page.getByRole('dialog').waitFor()
  await page.getByRole('button',{name:'Скасувати',exact:true}).click()
  check(posts===0,`${width}: cancel makes no write`)
  await page.getByRole('button',{name:'Зафіксувати місяць',exact:true}).click()
  const confirm=page.getByRole('button',{name:'Підтвердити фіксацію',exact:true})
  await confirm.evaluate(button=>{button.click();button.click()})
  await page.getByRole('dialog').getByRole('alert').waitFor()
  check(posts===1,`${width}: double click and unknown result do not duplicate close`)
  await confirm.click()
  await page.getByRole('dialog').waitFor({state:'hidden'})
  check(posts===2,`${width}: explicit retry resolves same month`)
  await page.getByRole('button',{name:'Переглянути збережений звіт',exact:true}).click()
  await page.getByText('Зафіксований звіт · 2024-03',{exact:true}).waitFor()
  await page.getByRole('region',{name:'Збережені місячні звіти'}).screenshot({path:`qa/output/financial-period-${width}.png`})
  check(new URL(page.url()).searchParams.get('snapshot')==='2024-03',`${width}: saved report has reloadable URL`)
  check(await page.getByText(/qa-admin/).isVisible(),`${width}: author and capture time visible`)
  check(await page.getByLabel('Історичний місяць',{exact:true}).count()===0,`${width}: saved view hides live period controls`)
  check(await page.getByText(/Рекламні витрати ·/).count()===0 && await page.getByLabel('Канал',{exact:true}).count()===0,`${width}: saved view excludes live spend and order listing`)
  const before=detailReads
  await page.evaluate(()=>{window.dispatchEvent(new Event('focus'));window.dispatchEvent(new CustomEvent('elfar:orders:changed'))})
  await page.waitForTimeout(250)
  check(detailReads===before,`${width}: focus and order events do not recalculate saved report`)
  const download=page.waitForEvent('download')
  await page.getByRole('button',{name:'CSV статистики',exact:true}).click()
  const file=await download;const content=readFileSync(await file.path(),'utf8')
  check(file.suggestedFilename()==='elfar-report-2024-03.csv' && content.includes('abc123') && content.includes('199.90'),`${width}: CSV exports saved amounts and identity`)
  await page.reload();await page.getByText('Зафіксований звіт · 2024-03',{exact:true}).waitFor()
  check(await page.getByText('Збережений звіт за 2024-03',{exact:true}).isVisible(),`${width}: saved mode survives reload`)
  detailFail=true
  await page.getByLabel('Перегляд звіту',{exact:true}).selectOption('2024-02')
  await page.getByText('Збережений звіт відсутній',{exact:true}).waitFor()
  check(await page.getByRole('button',{name:'CSV статистики',exact:true}).count()===0,`${width}: missing report never displays live financial data`)
  await page.getByRole('button',{name:'Повторити завантаження',exact:true}).click()
  await page.getByText('Зафіксований звіт · 2024-02',{exact:true}).waitFor()
  check(true,`${width}: saved report read can be retried`)
  captureHold=true;const ready=new Promise(resolve=>{heldReady=resolve})
  await page.getByLabel('Перегляд звіту',{exact:true}).selectOption('2024-03');await ready
  await page.getByLabel('Перегляд звіту',{exact:true}).selectOption('')
  await page.getByLabel('Історичний місяць',{exact:true}).waitFor();hold()
  await page.waitForTimeout(200)
  check(await page.getByText(/Зафіксований звіт ·/).count()===0 && await page.getByRole('button',{name:'CSV статистики',exact:true}).isVisible(),`${width}: late snapshot cannot replace live selection`)
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width}: no page overflow`)
  check(errors.length===0,`${width}: no React errors ${errors.join('; ')}`)
  await page.close()
 }
 const manager=await browser.newPage()
 await manager.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname
  const data=path.endsWith('/auth/session')?{role:'operator',name:'Manager',csrf_token:'qa'}:path.endsWith('/stats/report')?fixture:path.endsWith('/stats/months')?{months:['2024-02'],timezone:'Europe/Kyiv'}:path.endsWith('/stats/closed-periods')?{items:[]}:path.endsWith('/stats/spend')?[]:path.endsWith('/stats/order-sources')?{items:[],total:0}:{}
  await route.fulfill({json:data})
 })
 await manager.goto('http://127.0.0.1:5173/')
 await manager.getByRole('region',{name:'Збережені місячні звіти'}).waitFor()
 check(await manager.getByRole('button',{name:'Зафіксувати місяць',exact:true}).count()===0,'manager has read-only report controls')
 await manager.close()
 console.log(`FINANCIAL PERIODS BROWSER: ${checks}/${checks}`)
} finally {await browser.close()}
