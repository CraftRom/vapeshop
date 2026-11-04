import assert from 'node:assert/strict'
import {chromium} from 'playwright'
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH,args:['--no-sandbox','--disable-dev-shm-usage']})
let count=0
const check=(ok,label)=>{assert.ok(ok,label);count++;console.log('PASS '+label)}
const wait=ms=>new Promise(r=>setTimeout(r,ms))
const until=async fn=>{for(let i=0;i<100;i++){if(await fn())return;await wait(50)}throw Error('Condition timed out')}
const stamp='2026-10-16T07:00:00Z'
try{
 for(const width of [320,390,1280]){
  const page=await browser.newPage({viewport:{width,height:820},isMobile:width<760,hasTouch:width<760});page.setDefaultTimeout(15000)
  page.on('dialog',dialog=>dialog.accept());const errors=[];page.on('pageerror',e=>errors.push(e.message))
  const state={threads:[],messages:new Map(),replays:new Map(),posts:[],hold:null,fail:false,failCommit:false}
  const message=(id,text)=>({id,thread_id:1,text,author:'QA',direction:'out',created_at:stamp})
  await page.addInitScript(()=>{window.Telegram={WebApp:{initData:'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test',initDataUnsafe:{user:{id:123}},colorScheme:'dark',platform:'tdesktop',ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(fn){window.__supportBack=fn},offClick(){}}}}})
  await page.route('https://telegram.org/**',r=>r.fulfill({body:''}))
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();let json=[]
   if(path.endsWith('/config'))json={age_confirmed:true,currency:'грн',shop_name:'QA',bonus_enabled:false,payment_methods:[],delivery_methods:[]}
   else if(path.endsWith('/profile'))json={first_name:'QA',bonus_balance:'0',orders_count:0}
   else if(path.endsWith('/cart'))json={lines:[],subtotal:'0'}
   else if(path.endsWith('/orders'))json={items:[],total:0,has_more:false}
   else if(path==='/api/shop/support/threads'){
    if(method==='POST'){
     let thread=state.threads.find(t=>t.status==='open')
     if(!thread){thread={id:state.threads.length+1,status:'open',created_at:stamp};state.threads.unshift(thread);state.messages.set(thread.id,[])}
     json=thread
    }else json={items:state.threads,has_more:false}
   }else if(path.startsWith('/api/shop/support/threads/')){
    const id=Number(path.split('/')[5]),thread=state.threads.find(t=>t.id===id),items=state.messages.get(id)||[]
    if(path.endsWith('/close')){thread.status='closed';json=thread}
    else if(path.endsWith('/messages')){
     if(method==='POST'){
      const body=route.request().postDataJSON();state.posts.push(body)
      if(state.hold)await state.hold
      if(thread.status==='closed')return route.fulfill({status:409,json:{detail:'Звернення завершено'}})
      let saved=state.replays.get(body.request_id)
      if(!saved){saved={...message((items.at(-1)?.id||0)+1,body.text),thread_id:id,direction:'in'};items.push(saved);state.replays.set(body.request_id,saved)}
      if(state.failCommit){state.failCommit=false;return route.fulfill({status:503,json:{detail:'Невідомий результат надсилання'}})}
      json=saved
     }else{
      if(state.fail)return route.fulfill({status:503,json:{detail:'Переписка тимчасово недоступна'}})
      const q=url.searchParams
      const rows=q.has('before_id')?items.filter(m=>m.id<+q.get('before_id')).slice(-200):q.has('after_id')?items.filter(m=>m.id>+q.get('after_id')).slice(0,200):items.slice(-200)
      json={items:rows,thread,has_more:rows.length===200}
     }
    }else json=thread
   }
   await route.fulfill({json})
  })
  await page.goto((process.env.MINIAPP_URL||'http://127.0.0.1:5174')+'/app/')
  await page.getByRole('navigation').getByRole('button',{name:'Чат',exact:true}).click()
  await page.getByRole('button',{name:'Загальна підтримка',exact:true}).click()
  await page.getByRole('heading',{name:'Загальна підтримка',exact:true}).waitFor()
  check(state.threads.length===0,width+': viewing support creates no empty thread')
  await page.getByRole('button',{name:'Написати в підтримку',exact:true}).click()
  const log=page.getByRole('region',{name:'Переписка підтримки',exact:true}),input=page.getByPlaceholder('Повідомлення менеджеру'),send=page.getByRole('button',{name:'Надіслати',exact:true})
  await log.waitFor();check(state.threads.length===1,width+': explicit start creates a thread')
  await input.fill('Питання <b> & 😀');await send.click();await until(async()=>await input.inputValue()==='')
  check(state.messages.get(1).length===1,width+': first message saved once')
  state.messages.get(1).push(message(2,'Відповідь менеджера'))
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await log.getByText('Відповідь менеджера',{exact:true}).waitFor()
  check(true,width+': manager reply updates independently in background')
  await input.fill('Текст після надсилання');let release;state.hold=new Promise(r=>{release=r});const posts=state.posts.length
  await send.click();await until(()=>state.posts.length>posts)
  await input.fill('Наступна чернетка');state.hold=null;release();await until(async()=>await send.isEnabled())
  check(await input.inputValue()==='Наступна чернетка',width+': late response preserves newly typed text')
  await input.evaluate(el=>el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,isComposing:true})))
  check(state.posts.length===posts+1,width+': composing Enter does not send')
  // A send may finish after leaving and reopening the room.
  await input.fill('Надсилання під час переходу');let releaseAway;state.hold=new Promise(r=>{releaseAway=r});const awayPosts=state.posts.length
  await send.click();await until(()=>state.posts.length>awayPosts)
  await page.getByRole('button',{name:'Звернення',exact:true}).click()
  await page.getByRole('button').filter({hasText:'Звернення №1'}).click();await input.waitFor()
  check(await input.inputValue()==='Надсилання під час переходу',width+': navigation preserves pending draft')
  state.hold=null;releaseAway();await until(async()=>await input.inputValue()==='')
  check(true,width+': successful old send clears unchanged draft in remounted room')
  await input.fill('Другий перехід');let releaseNew;state.hold=new Promise(r=>{releaseNew=r});const newPosts=state.posts.length
  await send.click();await until(()=>state.posts.length>newPosts)
  await page.getByRole('button',{name:'Звернення',exact:true}).click()
  await page.getByRole('button').filter({hasText:'Звернення №1'}).click();await input.waitFor();await input.fill('Нова чернетка після переходу')
  state.hold=null;releaseNew();await until(()=>state.messages.get(1).some(m=>m.text==='Другий перехід'));await wait(100)
  check(await input.inputValue()==='Нова чернетка після переходу',width+': old send cannot clear edited draft after remount')
  // Persisted attempt survives a reload after server commit / response loss.
  state.failCommit=true;await input.fill('Повтор після втрати відповіді');await send.click()
  await page.getByText('Невідомий результат надсилання',{exact:false}).waitFor()
  const pending=state.posts.at(-1),beforeCount=state.messages.get(1).length
  await page.reload();await page.getByRole('navigation').getByRole('button',{name:'Чат',exact:true}).click()
  await page.getByRole('button',{name:'Загальна підтримка',exact:true}).click()
  await page.getByRole('button').filter({hasText:'Звернення №1'}).click();await input.waitFor()
  await input.fill('Повтор після втрати відповіді');await send.click();await until(async()=>await input.inputValue()==='')
  check(state.posts.at(-1).request_id===pending.request_id && state.messages.get(1).length===beforeCount,width+': replay after reload uses same key and no duplicate message')
  const existing=state.messages.get(1);for(let i=existing.at(-1).id+1;i<=451;i++)existing.push(message(i,'Історія '+i))
  await page.getByRole('button',{name:'Звернення',exact:true}).click()
  await page.getByRole('button').filter({hasText:'Звернення №1'}).click();await log.locator('[data-message-id="451"]').waitFor()
  check(await log.locator('[data-message-id]').count()===200,width+': initial page contains latest 200 replies')
  await page.getByRole('button',{name:'Раніші повідомлення',exact:true}).click();await until(async()=>await log.locator('[data-message-id]').count()===400)
  await page.getByRole('button',{name:'Раніші повідомлення',exact:true}).click();await until(async()=>await log.locator('[data-message-id]').count()===451)
  check(await log.locator('[data-message-id]').count()===451,width+': all 451 messages accessible without duplicates')
  await log.evaluate(el=>{el.scrollTop=200;el.dispatchEvent(new Event('scroll'))});const before=await log.evaluate(el=>el.scrollTop)
  existing.push(message(452,'Нова фонова відповідь'));await input.fill('Не губити чернетку')
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await log.getByText('Нова фонова відповідь',{exact:true}).waitFor()
  check(Math.abs(await log.evaluate(el=>el.scrollTop)-before)<3 && await input.inputValue()==='Не губити чернетку',width+': background reply preserves reading position and draft')
  state.fail=true;await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await page.getByText('Переписка тимчасово недоступна',{exact:false}).waitFor()
  check(await log.locator('[data-message-id]').count()===452 && await input.inputValue()==='Не губити чернетку',width+': polling error retains messages and draft')
  state.fail=false;await page.getByRole('button',{name:'Оновити чат',exact:true}).click();await until(async()=>await page.getByText('Переписка тимчасово недоступна',{exact:false}).count()===0)
  await page.getByRole('button',{name:'Завершити звернення',exact:true}).click();await until(async()=>await input.isDisabled())
  check(state.threads[0].status==='closed',width+': client close locks composer and keeps history')
  await page.getByRole('button',{name:'Звернення',exact:true}).click();await page.getByRole('button',{name:'Написати в підтримку',exact:true}).click();await input.waitFor()
  check(state.threads.length===2 && await input.inputValue()==='',width+': new question gets new thread and isolated draft')
  await page.evaluate(()=>window.__supportBack?.());await page.getByRole('heading',{name:'Загальна підтримка',exact:true}).waitFor()
  check(true,width+': Telegram Back returns from room to thread list')
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+': no horizontal page overflow')
  check(errors.length===0,width+': no React errors '+errors.join(';'))
  await page.close()
 }
}finally{await browser.close()}
console.log(`MINIAPP SUPPORT BROWSER: ${count}/${count}`)
