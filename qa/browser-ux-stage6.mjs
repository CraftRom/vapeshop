import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { readFileSync, mkdirSync } from 'node:fs'
const fixture=JSON.parse(readFileSync(new URL('./analytics-fixture.json',import.meta.url)))
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH,args:['--no-sandbox']})
let checks=0
const check=(ok,label)=>{assert.ok(ok,label);checks++;console.log('PASS '+label)}
const output=process.env.QA_OUTPUT_DIR||'qa/output';mkdirSync(output,{recursive:true})
const order=(id)=>({id,status:'new',total:'179.91',subtotal:'179.91',discount:'0',bonus_used:'0',payment_method:'card',items:[{id:1,name:'Тестовий товар із довгою назвою',price:'179.91',qty:1}],contact_name:'Тестовий покупець',contact_phone:'+380671234567',delivery_city:'Київ',delivery_address:'Відділення 1',created_at:'2026-10-14T08:00:00Z',can_chat:true,user:{tg_id:123},business_state:'pending'})
try {
 for(const width of [320,390,1280]){
  const p=await browser.newPage({viewport:{width,height:820}}),errors=[];p.on('pageerror',e=>errors.push(e.message))
  let restores=0, staffRole='admin', closedOrders=false
  await p.route('**/api/**',async route=>{
   const url=new URL(route.request().url()),path=url.pathname,q=url.searchParams;let data={}
   if(path.endsWith('/auth/session'))data={role:staffRole,name:'QA',csrf_token:'qa'}
   else if(path.endsWith('/stats/report'))data=structuredClone(fixture)
   else if(path.endsWith('/stats/months'))data={months:['2024-02'],timezone:'Europe/Kyiv'}
   else if(path.endsWith('/stats/order-sources'))data={total:0,items:[]}
   else if(path.endsWith('/stats/spend'))data=[]
   else if(path==='/api/orders'){const offset=Number(q.get('offset')||0);await new Promise(r=>setTimeout(r,80));data={items:Array.from({length:50},(_,i)=>({...order(offset+i+1), ...(closedOrders ? {status:'done',crm_id:'1',business_state:'sale'} : {})})),total:150,limit:50,offset,has_more:offset+50<150}}
   else if(/\/orders\/\d+$/.test(path))data=order(Number(path.split('/').pop()))
   else if(path.includes('/messages'))data=[]
   else if(path.includes('salesdrive-statuses'))data={statuses:[]}
   else if(path.endsWith('/backups/restore')){restores++;data={ok:true}}
   else if(path==='/api/backups')data={items:[{name:'qa-backup.dump',sizeBytes:12000,createdAt:'2026-10-14T08:00:00Z'}]}
   else if(path.includes('notifications'))data={items:[],unread:0}
   else if(path.includes('badges'))data={orders_new:0,support_unread:0}
   await route.fulfill({json:data})
  })
  await p.goto('http://127.0.0.1:5173/')
  const columns=p.getByRole('button',{name:'Колонки: Джерела',exact:true});await columns.waitFor();await columns.click()
  let dialog=p.getByRole('dialog',{name:'Колонки: Джерела',exact:true});await dialog.waitFor()
  check(await p.evaluate(()=>document.body.style.overflow==='hidden'),`${width}: columns lock background`)
  await dialog.getByLabel('ROAS',{exact:true}).uncheck();await dialog.getByRole('button',{name:'Готово',exact:true}).click()
  const region=p.getByRole('region',{name:'Таблиця: Джерела',exact:true})
  check(await region.getByRole('columnheader',{name:'ROAS',exact:true}).count()===0,`${width}: hidden column removed from visible table`)
  check(await region.getByRole('columnheader',{name:'Джерело',exact:true}).count()===1,`${width}: first column retained`)
  await p.reload();await columns.waitFor()
  check(await region.getByRole('columnheader',{name:'ROAS',exact:true}).count()===0,`${width}: columns persist after reload`)
  await columns.click();dialog=p.getByRole('dialog',{name:'Колонки: Джерела',exact:true});await dialog.waitFor()
  check(await dialog.getByLabel('Джерело',{exact:true}).isDisabled(),`${width}: identity column cannot be hidden`)
  await dialog.getByRole('button',{name:'Показати всі',exact:true}).click();await p.keyboard.press('Escape')
  check(await columns.evaluate(e=>e===document.activeElement),`${width}: columns Escape restores focus`)
  check(await region.getByRole('columnheader',{name:'ROAS',exact:true}).count()===1,`${width}: column reset restores data`)
  check(await region.getByRole('columnheader',{name:'Джерело',exact:true}).evaluate(e=>getComputedStyle(e).position==='sticky'),`${width}: first header sticky`)
  await p.screenshot({path:`${output}/analytics-stage6-${width}.png`,fullPage:true})
  check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width}: analytics fits viewport`)
  await p.goto('http://127.0.0.1:5173/orders?page=2&search=QA')
  await p.locator('.order-row').nth(49).waitFor()
  check(await p.locator('.order-row').first().getByRole('button',{name:'Стерти',exact:true}).isHidden(),`${width}: destructive action collapsed by default`)
  await p.evaluate(()=>window.scrollTo({top:1100,behavior:'instant'}))
  await p.waitForTimeout(100)
  const id=await p.locator('.order-row').evaluateAll(rows=>rows.find(r=>r.getBoundingClientRect().top>=100&&r.getBoundingClientRect().top<700)?.querySelector('.order-open').getAttribute('href'))
  assert.ok(id,'visible order link')
  await p.locator(`.order-open[href="${id}"]`).click();await p.getByRole('heading',{name:`Замовлення №${id.split('/').pop()}`,exact:true}).waitFor()
  await p.getByRole('button',{name:'← До списку',exact:true}).click()
  await p.locator('.order-row').nth(49).waitFor();await p.waitForTimeout(100)
  check(new URL(p.url()).searchParams.get('page')==='2'&&new URL(p.url()).searchParams.get('search')==='QA',`${width}: explicit return preserves filters and page`)
  check(await p.evaluate(()=>scrollY>500),`${width}: list position restored after asynchronous load`)
  await p.screenshot({path:`${output}/orders-stage6-${width}.png`})
  await p.goto('http://127.0.0.1:5173/backups')
  const restore=p.getByRole('button',{name:'Відновити',exact:true}).first();await restore.waitFor();await restore.click()
  dialog=p.getByRole('dialog',{name:'Відновити базу',exact:true});await dialog.waitFor()
  check(await p.evaluate(()=>document.body.style.overflow==='hidden'),`${width}: backup uses shared scroll lock`)
  check(await dialog.getByRole('button',{name:'Відновити',exact:true}).isDisabled(),`${width}: restore still requires exact filename`)
  await dialog.getByRole('textbox').fill('qa-backup.dump')
  check(await dialog.getByRole('button',{name:'Відновити',exact:true}).isEnabled(),`${width}: correct filename enables confirmation`)
  const buttons=dialog.getByRole('button');await buttons.last().focus();await p.keyboard.press('Tab')
  check(await buttons.first().evaluate(e=>e===document.activeElement),`${width}: backup traps keyboard focus`)
  await p.keyboard.press('Escape');check(await dialog.count()===0&&restores===0,`${width}: Escape closes without restore request`)
  staffRole='operator';closedOrders=true
  await p.goto('http://127.0.0.1:5173/orders');await p.locator('.order-row').nth(49).waitFor()
  check(await p.locator('.order-maintenance').count()===0,`${width}: no empty maintenance menu for closed CRM orders without delete rights`)
  check(!errors.length,`${width}: dashboard has no runtime errors`);await p.close()
  const store=await browser.newPage({viewport:{width,height:820}})
  await store.addInitScript(()=>{window.Telegram={WebApp:{initData:'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test',platform:'tdesktop',ready(){},expand(){},onEvent(){},offEvent(){}}}})
  await store.route('https://telegram.org/**',r=>r.fulfill({body:''}))
  await store.route('**/api/**',async r=>{
    const u=new URL(r.request().url()),path=u.pathname;let data=[]
    if(path.endsWith('/config'))data={age_confirmed:true,currency:'грн',bonus_enabled:false,referral_enabled:false}
    else if(path.endsWith('/categories'))data=[{id:1,name:'Товари',products_count:1},{id:2,name:'Скоро',products_count:0}]
    else if(path.endsWith('/products'))data=u.searchParams.get('category_id')==='2'?[]:[{id:1,name:'Тестовий товар',price:'10',stock:1}]
    else if(path.endsWith('/cart'))data={lines:[],subtotal:'0'}
    else if(path.endsWith('/profile'))data={first_name:'QA',orders_count:0,bonus_balance:0}
    await r.fulfill({json:data})
  })
  await store.goto('http://127.0.0.1:5174/app/');await store.locator('.store-card').first().waitFor()
  const tile=store.getByRole('button',{name:'Товари',exact:true})
  if(width<600)check(await tile.evaluate(e=>e.getBoundingClientRect().height<=80),`${width}: compact category height`)
  check(await store.locator('.availability-options button').evaluateAll(es=>es.every(e=>e.getBoundingClientRect().height>=44&&e.getBoundingClientRect().width>=44)),`${width}: touch controls stay at least 44px`)
  check(await store.locator('.availability-options button').evaluateAll(es=>es.every(e=>e.scrollWidth<=e.clientWidth)),`${width}: availability labels stay inside buttons`)
  check((await store.getByRole('button',{name:'Скоро',exact:true}).innerText()).includes('Незабаром'),`${width}: empty category explicitly upcoming`)
  check(await tile.locator('.taxonomy-count').getAttribute('title')==='Усього активних товарів у розділі, до пошуку та фільтра наявності',`${width}: category count distinguishes total from filtered result`)
  check(await store.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width}: compact catalog fits viewport`)
  await store.screenshot({path:`${output}/catalog-stage6-${width}.png`});await store.close()
 }
}finally{await browser.close()}
console.log(`STAGE6 UX BROWSER: ${checks}/${checks}`)
