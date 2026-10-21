import { chromium } from 'playwright'
import assert from 'node:assert/strict'
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH,args:['--no-sandbox','--disable-dev-shm-usage']})
let checks=0
const check=(ok,label)=>{assert.ok(ok,label);checks++;console.log('PASS '+label)}
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms))
const message=id=>({id,thread_id:1,user_id:1,direction:id%5===0?'out':'in',is_read:false,author:'QA',text:`Репліка ${id}. Повна історія звернення підтримки.`,created_at:'2026-10-21T08:00:00Z'})
const thread=id=>({id,user_id:id,status:id===2?'closed':'open',unread_count:0,user:{first_name:`QA ${id}`,tg_id:id},created_at:'2026-10-21T08:00:00Z'})
async function wake(page){await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await pause(150)}
async function anchor(log){return log.evaluate(el=>{const top=el.getBoundingClientRect().top;const item=[...el.querySelectorAll('[data-message-id]')].find(x=>x.getBoundingClientRect().bottom>top);return {id:item?.dataset.messageId,offset:item?.getBoundingClientRect().top-top}})}
async function sameAnchor(log,prior,label){const offset=await log.evaluate((el,id)=>el.querySelector(`[data-message-id="${id}"]`)?.getBoundingClientRect().top-el.getBoundingClientRect().top,prior.id);check(Math.abs(offset-prior.offset)<4,label)}
try {
 for(const width of [320,390,1280]){
  const page=await browser.newPage({viewport:{width,height:850},isMobile:width<760,hasTouch:width<760})
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.addInitScript(()=>{window.qaHidden=true;Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.qaHidden})})
  const data={1:Array.from({length:650},(_,i)=>message(i+1)),2:[{...message(2001),thread_id:2,text:'Інше завершене звернення'}],3:[],acks:[],gets:[],ackFail:true,olderFail:true,holdOlder:false,release:null,ready:null}
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url()),path=url.pathname,q=url.searchParams,method=route.request().method();let json={}
   if(path==='/api/auth/session')json={role:'admin',name:'QA',csrf_token:'qa',draft_scope:'support-history-qa'}
   else if(path==='/api/support')json=[thread(1),thread(2),thread(3)]
   else if(path==='/api/support/stats')json={open:2,closed:1,total:3,clients:3,unread:1}
   else if(/^\/api\/support\/\d+$/.test(path))json=thread(Number(path.split('/').at(-1)))
   else if(path.endsWith('/messages/read')){
    const id=Number(path.split('/').at(-3)),ids=route.request().postDataJSON().message_ids
    data.acks.push({id,ids})
    assert.equal(route.request().headers()['x-csrf-token'],'qa',`${width}: ACK uses CSRF session`)
    if(data.ackFail)return route.fulfill({status:503,json:{detail:'ACK unavailable'}})
    json={marked:ids.length}
   } else if(/^\/api\/support\/\d+\/messages$/.test(path)){
    const id=Number(path.split('/').at(-2)),items=structuredClone(data[id]);data.gets.push({id,q:Object.fromEntries(q)})
    assert.notEqual(q.get('mark_read'),'true',`${width}: history GET has no blanket read side effect`)
    if(q.has('before_id')&&data.olderFail){data.olderFail=false;return route.fulfill({status:503,json:{detail:'Older unavailable'}})}
    json=q.has('before_id')?items.filter(x=>x.id<Number(q.get('before_id'))).slice(-200):q.has('after_id')?items.filter(x=>x.id>Number(q.get('after_id'))).slice(0,200):items.slice(-200)
    if(q.has('before_id')&&data.holdOlder){data.holdOlder=false;await new Promise(resolve=>{data.release=resolve;data.ready?.()})}
   } else if(path.includes('badges'))json={orders_new:0,support_unread:1}
   else if(path.includes('notifications'))json={items:[],unread:0}
   await route.fulfill({json})
  })
  await page.goto('http://127.0.0.1:5173/support?thread=1')
  let log=page.getByRole('region',{name:'Переписка підтримки',exact:true})
  await log.locator('[data-message-id="650"]').waitFor();await pause(100)
  check(await log.locator('[data-message-id]').count()===200,`${width}: initial view is latest 200 of 650`)
  check(data.acks.length===0,`${width}: hidden document never sends read ACK`)
  check(await log.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight<4),`${width}: opens at latest reply`)
  const visible=await log.evaluate(el=>{const r=el.getBoundingClientRect();return [...el.querySelectorAll('[data-message-id]')].filter(n=>{const b=n.getBoundingClientRect();return b.bottom>Math.max(r.top,0)&&b.top<Math.min(r.bottom,innerHeight)}).map(n=>Number(n.dataset.messageId))})
  await page.evaluate(()=>{window.qaHidden=false;document.dispatchEvent(new Event('visibilitychange'))})
  await page.getByRole('button',{name:'Повторити позначення',exact:true}).waitFor()
  if(process.env.QA_CAPTURE_DIR)await page.screenshot({path:`${process.env.QA_CAPTURE_DIR}/support-history-error-${width}.png`})
  check(data.acks[0].ids.length>0 && data.acks[0].ids.every(id=>visible.includes(id)&&id%5!==0),`${width}: ACK includes only visible incoming bubbles`)
  check(data.acks.every(a=>a.ids.every(id=>id>450)),`${width}: unloaded history remains unread`)
  const retried=page.getByRole('button',{name:'Повторити позначення',exact:true}).evaluate(button=>button.click())
  data.ackFail=false;await retried
  await page.getByRole('button',{name:'Повторити позначення',exact:true}).waitFor({state:'hidden'})
  check(data.acks.length>=2,`${width}: failed ACK can be explicitly retried`)
  const compose=page.locator('.support-compose textarea');await compose.fill('Збережена чернетка історії')
  await log.evaluate(el=>{el.scrollTop=0});await pause(80)
  await page.getByRole('button',{name:'Показати попередні повідомлення',exact:true}).evaluate(b=>b.click())
  await page.getByRole('button',{name:'Повторити історію',exact:true}).waitFor()
  check(await log.locator('[data-message-id]').count()===200,`${width}: older page failure preserves loaded messages`)
  let prior=await anchor(log);data.holdOlder=true
  const ready=new Promise(resolve=>{data.ready=resolve})
  await page.getByRole('button',{name:'Повторити історію',exact:true}).evaluate(b=>{b.click();b.click()});await ready;await pause(100);prior=await anchor(log)
  data[1].push(message(651));await wake(page);await log.locator('[data-message-id="651"]').waitFor()
  await sameAnchor(log,prior,`${width}: incoming reply preserves reading anchor while older page waits`)
  data.release();await log.locator('[data-message-id="251"]').waitFor()
  await sameAnchor(log,prior,`${width}: prepend keeps the same visible reply and offset`)
  // The error notice disappeared when retry began; compare the current anchor
  // across the actual prepend rather than across that explicit UI dismissal.
  if(process.env.QA_CAPTURE_DIR)await page.screenshot({path:`${process.env.QA_CAPTURE_DIR}/support-history-${width}.png`})
  check(await log.locator('[data-message-id]').count()===401,`${width}: older page and concurrent reply retained once`)
  check(await compose.inputValue()==='Збережена чернетка історії',`${width}: draft survives prepend and polling`)
  let before=await anchor(log)
  const last=data[1].at(-1).id;for(let i=1;i<=450;i++)data[1].push(message(last+i))
  await wake(page);await log.locator(`[data-message-id="${last+450}"]`).waitFor()
  await sameAnchor(log,before,`${width}: large delta backlog keeps current reply in place`)
  check(await log.locator('[data-message-id]').count()===851,`${width}: >200 new replies drain without gaps`)
  for(let pass=0;pass<3;pass++){
   await log.evaluate(el=>{el.scrollTop=0});await pause(50)
   if(!await page.getByRole('button',{name:'Показати попередні повідомлення',exact:true}).count())break
   const oldCount=await log.locator('[data-message-id]').count()
   await page.getByRole('button',{name:'Показати попередні повідомлення',exact:true}).evaluate(b=>b.click())
   await page.waitForFunction(n=>document.querySelectorAll('.support-chat-log [data-message-id]').length>n||!document.querySelector('.chat-history-more button'),oldCount)
  }
  check(await log.locator('[data-message-id]').count()===data[1].length,`${width}: complete 1101-message history available`)
  check(await log.locator('[data-message-id="1"]').count()===1,`${width}: first reply is reachable once`)
  await page.getByRole('button',{name:/Нові повідомлення:|До останніх повідомлень/}).click();await pause(100)
  check(await log.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight<4),`${width}: explicit jump reaches latest reply`)
  // Reopen to create an older-page request, then leave before it returns.
  await page.reload();await log.locator('[data-message-id="1101"]').waitFor()
  await page.evaluate(()=>{window.qaHidden=false;document.dispatchEvent(new Event('visibilitychange'))})
  await log.evaluate(el=>{el.scrollTop=0});data.holdOlder=true
  const oldReady=new Promise(resolve=>{data.ready=resolve})
  await page.getByRole('button',{name:'Показати попередні повідомлення',exact:true}).evaluate(b=>b.click());await oldReady
  if(width<760)await page.getByRole('button',{name:'← Назад',exact:true}).click()
  await page.locator('.support-session').filter({hasText:'#2'}).click()
  await log.locator('[data-message-id="2001"]').waitFor();data.release();await pause(150)
  check(await log.locator('[data-message-id]').count()===1,`${width}: late history response cannot contaminate another thread`)
  check(await page.locator('.support-compose textarea').count()===0,`${width}: closed thread stays read-only`)
  if(width<760)await page.getByRole('button',{name:'← Назад',exact:true}).click()
  await page.locator('.support-session').filter({hasText:'#3'}).click()
  await page.getByText('Повідомлень ще немає.',{exact:true}).waitFor()
  data[3]=Array.from({length:451},(_,i)=>({...message(3001+i),thread_id:3}))
  await wake(page);await log.locator('[data-message-id="3451"]').waitFor()
  check(await log.locator('[data-message-id]').count()===451,`${width}: empty initial chat catches first large batch from cursor zero`)
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width}: no horizontal overflow`)
  check(data.gets.every(call=>call.q.mark_read!=='true'),`${width}: every history GET is read-only`)
  check(data.acks.length>0,`${width}: authenticated ACK transport exercised`)
  check(errors.length===0,`${width}: no React errors ${errors.join('; ')}`)
  await page.close()
 }
 console.log(`SUPPORT HISTORY BROWSER: ${checks}/${checks}`)
} finally {await browser.close()}
