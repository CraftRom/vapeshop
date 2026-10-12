import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || undefined, args: ['--no-sandbox'] })
let count = 0
const check = (ok,label) => { assert.ok(ok,label); count++; console.log(`PASS ${label}`) }
const pause = (ms) => new Promise(resolve => setTimeout(resolve,ms))
const order = (id,name='Тест',status='done') => ({ id, status, total:'10',subtotal:'10',items:[],contact_name:name,contact_phone:'1',created_at:'2026-10-12T12:00:00Z',can_cancel:false })
const customer = (id,name='Тест') => ({id,tg_id:id,first_name:name,created_at:'2026-10-12T12:00:00Z',orders_count:0,bonus_balance:0,total_spent:0})
const envelope = (items,total,params) => ({items,total,limit:Number(params.get('limit')||20),offset:Number(params.get('offset')||0),has_more:Number(params.get('offset')||0)+items.length<total})
async function staff(path) {
 const page=await browser.newPage({viewport:{width:1280,height:820}})
 const errors=[];page.on('pageerror',error=>errors.push(error.message))
 const state={calls:[],fail:false,modalOrdersFail:false,modalSavedFail:false,hold:false}
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()), p=url.pathname, q=url.searchParams
  let data={}
  if(p==='/api/auth/session')data={role:'operator',name:'QA',csrf_token:'qa'}
  else if(p.includes('notifications'))data={items:[],unread:0}
  else if(p.includes('badges'))data={orders_new:0,support_unread:0}
  else if(p.includes('salesdrive-statuses'))data={statuses:[{id:'1',name:'Новий'},{id:'2',name:'Продаж'}]}
  else if(p.includes('unread'))data={}
  else if(p.match(/customers\/\d+\/orders/)){
   if(state.modalOrdersFail){await route.fulfill({status:503,json:{detail:'Помилка історії клієнта'}});return}
   data=envelope([order(Number(q.get('offset')||0)+1)],235,q)
  } else if(p.match(/customers\/\d+\/wishlists/)){
   if(state.modalSavedFail){await route.fulfill({status:503,json:{detail:'Помилка списків клієнта'}});return}
   data=[{id:1,name:'Улюблене',size:1,products:[{id:1,name:'Збережений товар',price:10,is_active:true,stock:1}]}]
  } else if(p==='/api/orders'||p==='/api/customers'){
   state.calls.push(Object.fromEntries(q))
   const term=q.get('search')||q.get('crm_status_id')||q.get('date_from')||''
   const fail=state.fail||term==='OLDFAIL'
   if(term==='OLD'||term==='OLDFAIL'||term==='1'||term==='2026-10-11')await pause(1200)
   if(state.hold)await pause(700)
   if(fail){await route.fulfill({status:503,json:{detail:'Збій списку'}});return}
   const offset=Number(q.get('offset')||0),total=term?1:135
   const items=Array.from({length:Math.min(50,total-offset)},(_,i)=>p.endsWith('orders')?order(offset+i+1,term||'Тест'):customer(offset+i+1,term||'Тест'))
   data=envelope(items,total,q)
  }
  await route.fulfill({json:data})
 })
 await page.goto('http://127.0.0.1:5173/'+path)
 await page.getByRole('navigation',{name:'Сторінки списку'}).waitFor()
 return {page,state,errors}
}
async function store(width=390, initial={}) {
 const page=await browser.newPage({viewport:{width,height:820}}),errors=[]
 page.on('pageerror',error=>errors.push(error.message))
 const state={failCart:true,failProfile:false,failOrders:false,failSaved:false,moreFail:false,calls:[],total:45,baseId:45,...initial}
 await page.addInitScript(()=>{window.Telegram={WebApp:{initData:'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test',initDataUnsafe:{user:{id:123}},platform:'tdesktop',ready(){},expand(){},disableVerticalSwipes(){},onEvent(){},offEvent(){}}}})
 await page.route('https://telegram.org/**',r=>r.fulfill({body:''}))
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),p=url.pathname,q=url.searchParams
  let data=[]
  if(p.endsWith('/config'))data={age_confirmed:true,currency:'грн',bonus_enabled:true,referral_enabled:false}
  else if(p.endsWith('/cart')){
   if(state.failCart){await route.fulfill({status:503,json:{detail:'Кошик недоступний'}});return}
   data={lines:[],subtotal:0}
  }else if(p.endsWith('/profile')){
   if(state.failProfile){await route.fulfill({status:503,json:{detail:'Профіль недоступний'}});return}
   data={first_name:'Дмитро',orders_count:45,total_spent:450,bonus_balance:7}
  }else if(p.endsWith('/orders/active')){
   if(state.failActive){await route.fulfill({status:503,json:{detail:'Активні замовлення недоступні'}});return}
   data=[order(1,'Давнє активне','accepted')]
  }
  else if(p.endsWith('/orders')){
   state.calls.push(Object.fromEntries(q))
   if(state.failOrders||state.moreFail&&Number(q.get('offset'))>=20){await route.fulfill({status:503,json:{detail:'Історія недоступна'}});return}
   const offset=Number(q.get('offset')||0)
   data=envelope(Array.from({length:Math.min(20,state.total-offset)},(_,i)=>order(state.baseId-offset-i)),state.total,q)
  }else if(p.endsWith('/wishlists')){
   if(state.failSaved){await route.fulfill({status:503,json:{detail:'Списки недоступні'}});return}
   data=[]
  }
  await route.fulfill({json:data})
 })
 await page.goto('http://127.0.0.1:5174/app/')
 await page.getByRole('button',{name:'Профіль',exact:true}).click()
 return {page,state,errors}
}
try {
 for(const path of ['orders','customers']){
  const {page,state,errors}=await staff(path)
  const list=page.locator(path==='orders'?'.orders-list':'.table-wrap')
  const input=path==='orders'?page.getByRole('searchbox'):page.getByPlaceholder("Ім'я, username або телефон")
  check((await page.getByRole('navigation',{name:'Сторінки списку'}).innerText()).includes('135'),'точний total '+path)
  await page.getByRole('button',{name:'Наступна',exact:true}).click()
  await page.waitForFunction(()=>new URL(location.href).searchParams.get('page')==='2')
  await page.waitForFunction(()=>document.querySelector('[aria-label="Сторінки списку"]')?.textContent.includes('Сторінка 2'))
  check(state.calls.at(-1).offset==='50',path+': наступна сторінка API')
  await input.fill('OLD');await page.waitForResponse(r=>r.url().includes('search=OLD'),{timeout:4000}).catch(()=>{})
  // Start another OLD refresh and replace the filter while it is still running.
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('elfar:orders:changed')))
  await pause(180)
  await input.fill('NEW')
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  check(!(await list.textContent().catch(()=>''))?.includes('OLD'),path+': старі дані сховані під новим фільтром')
  await list.getByText('NEW',{exact:false}).waitFor()
  await pause(1400)
  check(!(await list.textContent()).includes('OLD'),path+': стара live-відповідь не перезаписує NEW')
  check(!new URL(page.url()).searchParams.has('page'),path+': фільтр скидає сторінку')
  await input.fill('OLDFAIL');await pause(430);await input.fill('NEW')
  await list.getByText('NEW',{exact:false}).waitFor();await pause(1600)
  check(await page.getByText('Збій списку',{exact:true}).count()===0,path+': стара помилка не застосована')
  state.fail=true
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('elfar:orders:changed')))
  await page.getByRole('button',{name:'Спробувати ще раз',exact:true}).waitFor()
  check((await list.textContent()).includes('NEW') && (await page.getByText('Показано попередні дані.',{exact:false}).count())>0,path+': збережено дані з позначкою застарілості')
  state.fail=false;await page.getByRole('button',{name:'Спробувати ще раз',exact:true}).click()
  await page.waitForFunction(()=>!document.querySelector('.error-bar'))
  if(path==='orders'){
   await input.fill('');await page.waitForFunction(()=>!new URL(location.href).searchParams.has('search'))
   const select=page.locator('.filter-status select')
   await select.selectOption('crm:1');await page.waitForFunction(()=>new URL(location.href).searchParams.get('status')==='crm:1');await pause(100);await select.selectOption('crm:2')
   await list.getByText('2',{exact:true}).first().waitFor();await pause(1400)
   check(!(await list.textContent()).includes('\n1\n'),'status reverse response uses latest')
   await select.selectOption('');await page.locator('input[type=date]').first().fill('2026-10-11');await pause(80);await page.locator('input[type=date]').first().fill('2026-10-12')
   await list.getByText('2026-10-12',{exact:true}).waitFor();await pause(1400)
   check(!(await list.textContent()).includes('2026-10-11'),'date reverse response uses latest')
  }else{
   state.modalOrdersFail=true;state.modalSavedFail=true
   await page.getByRole('button',{name:'Замовлення',exact:true}).first().click()
   await page.getByRole('button',{name:'Повторити замовлення'}).waitFor();await page.getByRole('button',{name:'Повторити списки'}).waitFor()
   check(await page.getByText('Клієнт ще нічого не замовляв.').count()===0,'modal errors never say empty')
   state.modalOrdersFail=false;await page.getByRole('button',{name:'Повторити замовлення'}).click()
   await page.getByRole('dialog').getByText('Усього:',{exact:false}).waitFor()
   check(await page.getByRole('button',{name:'Повторити списки'}).isVisible(),'modal orders success independent of lists error')
   state.modalSavedFail=false;await page.getByRole('button',{name:'Повторити списки'}).click();await page.getByText('Збережений товар —',{exact:false}).waitFor()
   check(true,'modal lists retry recovers data')
  }
  await page.setViewportSize({width:360,height:820})
  check(await page.getByRole('button',{name:'Наступна',exact:true}).first().isVisible(),path+': навігація видима на телефоні')
  check(!errors.length,path+': без runtime errors '+errors.join('; '));await page.close()
 }
 for(const width of [320,390,1280]){
  const {page,state,errors}=await store(width)
  await page.getByText('Історія замовлень',{exact:true}).waitFor();await page.getByText('№45',{exact:true}).waitFor()
  check(await page.locator('.stat').getByText('45',{exact:true}).isVisible(),width+': cart 503 does not block profile')
  check(await page.getByRole('button',{name:'Показати ще'}).isVisible(),width+': history pagination available')
  state.moreFail=true;await page.getByRole('button',{name:'Показати ще'}).click();await page.getByRole('button',{name:'Повторити: Історія замовлень'}).waitFor()
  check(await page.getByText('№45',{exact:true}).isVisible() && await page.getByText('Історія замовлень поки порожня',{exact:true}).count()===0,width+': failed next page retains history')
  state.moreFail=false;await page.getByRole('button',{name:'Повторити: Історія замовлень'}).click();await page.getByText('№6',{exact:true}).waitFor()
  await page.getByRole('button',{name:'Показати ще'}).click();await page.getByText('№1',{exact:true}).waitFor()
  check(await page.locator('.order').count()===45 && await page.getByRole('button',{name:'Показати ще'}).count()===0,width+': complete history and no duplicates')
  // Reconcile all opened pages when new data shifts the prefix.
  state.baseId=46;state.total=46
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await page.getByText('№46',{exact:true}).waitFor()
  check(await page.locator('.order').count()===46 && await page.getByText('№1',{exact:true}).isVisible(),width+': polling preserves opened history after new order')
  state.failOrders=true;state.failSaved=true;state.failProfile=true
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await page.getByRole('button',{name:'Повторити: Профіль'}).waitFor()
  check(await page.getByText('№46',{exact:true}).isVisible(),width+': independent failures retain successful prior history')
  await page.getByRole('button',{name:'Чат',exact:true}).click();await page.getByRole('button',{name:/№1/}).waitFor()
  check(true,width+': old active order available despite history failure')
  await page.getByRole('button',{name:'Кошик',exact:true}).click();await page.getByRole('button',{name:'Повторити: Кошик'}).waitFor()
  check(await page.getByText('Кошик поки порожній',{exact:true}).count()===0,width+': failed cart not presented as empty')
  state.failCart=false;await page.getByRole('button',{name:'Повторити: Кошик'}).click();await page.getByText('Кошик поки порожній',{exact:true}).waitFor()
  check(true,width+': independent retry recovers cart')
  check(!errors.length,width+': no runtime errors '+errors.join('; '));await page.close()
 }
 {
  const {page,state,errors}=await store(390,{failCart:false,failOrders:true,failSaved:true,failProfile:true,failActive:true})
  await page.getByRole('button',{name:'Повторити: Профіль'}).waitFor()
  await page.getByRole('button',{name:'Повторити: Історія замовлень'}).waitFor()
  await page.getByRole('button',{name:'Повторити: Збережені списки'}).waitFor()
  check(await page.getByText('Історія замовлень поки порожня',{exact:true}).count()===0,'initial history failure is not an empty history')
  state.failOrders=false;await page.getByRole('button',{name:'Повторити: Історія замовлень'}).click()
  await page.getByText('№45',{exact:true}).waitFor()
  check(await page.getByRole('button',{name:'Повторити: Профіль'}).isVisible(),'history loads independently when profile remains unavailable')
  state.failProfile=false;state.failSaved=false
  await page.getByRole('button',{name:'Повторити: Профіль'}).click()
  await page.getByRole('button',{name:'Повторити: Збережені списки'}).click()
  await page.locator('.stat').getByText('45',{exact:true}).waitFor()
  await page.getByRole('button',{name:'Чат',exact:true}).click()
  await page.getByRole('button',{name:'Повторити: Активні замовлення'}).waitFor()
  check(await page.getByText('Активних замовлень зараз немає',{exact:true}).count()===0,'failed active orders are not presented as empty chats')
  state.failActive=false;await page.getByRole('button',{name:'Повторити: Активні замовлення'}).click()
  await page.getByRole('button',{name:/№1/}).waitFor()
  check(true,'active orders retry independent of history')
  check(!errors.length,'initial failed resources recover without runtime errors')
  await page.close()
 }
 console.log(`WORKING DATA BROWSER: ${count}/${count}`)
}finally{await browser.close()}
