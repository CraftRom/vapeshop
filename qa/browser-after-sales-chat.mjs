import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH||undefined,args:['--no-sandbox']})
let checks=0
const check=(ok,label)=>{assert.ok(ok,label);checks++;console.log('PASS '+label)}
const pause=ms=>new Promise(r=>setTimeout(r,ms))
try {
 for(const width of [1280,390,320]) {
  const page=await browser.newPage({viewport:{width,height:820}})
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  const state={acks:[],older:[],failOlder:false,access:true,hold:null,initialFail:false}
  const messages=Array.from({length:451},(_,i)=>({id:i+1,direction:i%2?'in':'out',author:'Менеджер',text:`Повідомлення ${i+1} — історія замовлення`,created_at:'2026-10-13T13:00:00Z'}))
  const order={id:7,status:'done',status_label:'Виконано',total:'19.90',created_at:'2026-09-01T12:00:00Z',completed_at:'2026-10-13T13:00:00Z',can_chat:true,chat_until:'2026-10-20T13:00:00Z',items:[]}
  await page.addInitScript(()=>{window.Telegram={WebApp:{initData:'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test',initDataUnsafe:{user:{id:123}},platform:'tdesktop',ready(){},expand(){},disableVerticalSwipes(){},onEvent(){},offEvent(){}}}})
  await page.route('https://telegram.org/**',r=>r.fulfill({body:''}))
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url()),p=url.pathname,q=url.searchParams,method=route.request().method()
   let data=[]
   if(p.endsWith('/config'))data={age_confirmed:true,currency:'грн',bonus_enabled:true,referral_enabled:false}
   else if(p.endsWith('/cart'))data={lines:[],subtotal:0}
   else if(p.endsWith('/profile'))data={orders_count:1,total_spent:19.90,bonus_balance:0}
   else if(p.endsWith('/orders/chattable'))data=[order]
   else if(p.endsWith('/orders'))data=q.get('paginated')?{items:[order],total:1,has_more:false}:[order]
   else if(p.endsWith('/chat/access'))data={can_chat:state.access,chat_until:order.chat_until,completed_at:order.completed_at}
   else if(p.endsWith('/chat/read')){state.acks.push(route.request().postDataJSON().message_ids);data={marked:1}}
   else if(p.endsWith('/chat')&&method==='POST'){data={id:452,direction:'in',text:route.request().postDataJSON().text,created_at:order.completed_at};messages.push(data)}
   else if(p.endsWith('/chat')){
    if(q.has('before_id')){
     const before=Number(q.get('before_id'));state.older.push(before)
     if(state.failOlder){await route.fulfill({status:503,json:{detail:'Історія тимчасово недоступна'}});return}
     data=messages.filter(m=>m.id<before).slice(-Number(q.get('limit')||200))
    }else if(q.has('after_id'))data=messages.filter(m=>m.id>Number(q.get('after_id'))).slice(0,200)
    else {if(state.initialFail){await route.fulfill({status:503,json:{detail:'Чат недоступний'}});return}data=messages.slice(-200)}
   }
   await route.fulfill({json:data})
  })
  await page.goto((process.env.MINIAPP_URL||'http://127.0.0.1:5174')+'/app/?chat=7')
  await page.getByRole('heading',{name:'Замовлення №7'}).waitFor()
  await page.locator('[data-message-id="451"]').waitFor()
  check(await page.getByText('Писати менеджеру можна до',{exact:false}).isVisible(),'after-sales deadline '+width)
  check(await page.locator('.bubble').count()===200,'initial 200 replies '+width)
  await page.waitForFunction(()=>document.querySelector('.chat-log').scrollTop>0)
  await pause(250)
  check(state.acks.flat().length>0 && state.acks.flat().every(id=>id>=252&&id<=451&&id%2===1),'ACK only visible issued outgoing IDs '+width)
  check(!state.acks.flat().includes(253),'offscreen fetched message stays unread '+width)
  await page.locator('.chat-log').evaluate(el=>el.scrollTop=0)
  await page.getByRole('button',{name:'Раніші повідомлення',exact:true}).waitFor()
  state.failOlder=true
  await page.getByRole('button',{name:'Раніші повідомлення',exact:true}).click()
  await page.getByText('Історія тимчасово недоступна',{exact:false}).waitFor()
  check(await page.locator('.bubble').count()===200,'history error preserves loaded page '+width)
  state.failOlder=false
  await page.getByRole('button',{name:'Повторити',exact:true}).click()
  await page.locator('[data-message-id="52"]').waitFor()
  check(await page.locator('.bubble').count()===400,'older 200 merged '+width)
  const log=page.locator('.chat-log')
  const anchor=await log.evaluate(el=>{const edge=el.getBoundingClientRect().top;return [...el.querySelectorAll('[data-message-id]')].find(n=>n.getBoundingClientRect().bottom>edge)?.dataset.messageId})
  check(await page.locator('[data-message-id="252"]').evaluate(el=>{const rect=el.getBoundingClientRect(),root=el.parentElement.getBoundingClientRect();return rect.top<root.bottom&&rect.bottom>root.top}),'loading older preserves original visible message '+width)
  await log.evaluate(el=>el.scrollTop=0)
  await page.getByRole('button',{name:'Раніші повідомлення',exact:true}).click()
  await page.locator('[data-message-id="1"]').waitFor()
  check(await page.locator('.bubble').count()===451,'entire 451-message history '+width)
  check(await page.getByText('Початок історії',{exact:true}).count()===1,'history end has explicit state '+width)
  check(state.older.filter((x,i,a)=>i===0||x!==a[i-1]).join(',')==='252,52','before_id cursors '+width)
  const firstBefore=await log.evaluate(el=>{const edge=el.getBoundingClientRect().top;return [...el.querySelectorAll('[data-message-id]')].find(n=>n.getBoundingClientRect().bottom>edge)?.dataset.messageId})
  messages.push({id:452,direction:'out',text:'Нова відповідь після повернення',created_at:order.completed_at})
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await page.locator('[data-message-id="452"]').waitFor()
  const firstAfter=await log.evaluate(el=>{const edge=el.getBoundingClientRect().top;return [...el.querySelectorAll('[data-message-id]')].find(n=>n.getBoundingClientRect().bottom>edge)?.dataset.messageId})
  check(firstBefore===firstAfter,'delta reply preserves older reading position '+width)
  check(!state.acks.flat().includes(452),'offscreen live reply not acknowledged '+width)
  await log.evaluate(el=>el.scrollTop=el.scrollHeight)
  await pause(250)
  check(state.acks.flat().includes(452),'live reply ACK after scrolling into view '+width)
  const ackCount=state.acks.length
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));document.querySelector('.chat-log').scrollTop=0})
  await pause(250)
  check(state.acks.length===ackCount,'hidden tab does not acknowledge scrolled replies '+width)
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))})
  state.access=false
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await page.getByText('Чат замовлення закрито.',{exact:false}).waitFor()
  check(await page.getByRole('button',{name:'Надіслати',exact:true}).isDisabled(),'expiry disables send '+width)
  check(await page.locator('input[type=file]').isDisabled(),'expiry disables attachment '+width)
  check(await page.locator('.bubble').count()===452,'expiry keeps loaded history '+width)
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'no horizontal overflow '+width)
  check(await log.evaluate(el=>el.clientHeight>100&&el.scrollHeight>el.clientHeight),'chat has real scroll viewport '+width)
  check(await page.evaluate(()=>{const log=document.querySelector('.chat-log').getBoundingClientRect(),compose=document.querySelector('.chat-compose').getBoundingClientRect();return log.bottom<=compose.top+1}),'composer does not cover history '+width)
  check(await page.evaluate(()=>document.querySelector('.chat-compose').getBoundingClientRect().bottom<=document.querySelector('.store-nav').getBoundingClientRect().top+1),'composer stays above navigation '+width)
  check(errors.length===0,'no React errors '+width)
  if(process.env.QA_CAPTURE_DIR)await page.screenshot({path:`${process.env.QA_CAPTURE_DIR}/stage4-chat-${width}.png`})
  await page.getByRole('button',{name:'Профіль',exact:true}).click()
  const historyButton=page.getByRole('button',{name:'Чат з менеджером',exact:true})
  await historyButton.waitFor()
  await historyButton.click()
  await page.getByRole('heading',{name:'Замовлення №7'}).waitFor()
  await page.getByText('Чат замовлення закрито.',{exact:false}).waitFor()
  check(await page.locator('.bubble').count()===200,'profile opens read-only chat history '+width)
  check(await page.getByRole('button',{name:'Надіслати',exact:true}).isDisabled(),'profile cannot bypass expired chat '+width)
  await page.close()
 }
 console.log(`AFTER-SALES CHAT BROWSER: ${checks}/${checks}`)
} finally {await browser.close()}
