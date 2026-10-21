import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH || undefined, args:['--no-sandbox']})
const base = process.env.DASHBOARD_URL || 'http://127.0.0.1:5173'
const A = 'a'.repeat(64), B = 'b'.repeat(64), prefix = 'elfar:chat-draft:v1:'
let checks = 0
function check(ok, label) { assert.ok(ok, label); checks++; console.log('PASS ' + label) }
const pause = ms => new Promise(resolve => setTimeout(resolve, ms))
const until = async fn => { for (let i=0;i<100;i++) { if (await fn()) return; await pause(50) } throw Error('Condition timed out') }
const order = { id:7,status:'accepted',can_chat:true,total:'100',subtotal:'100',items:[],payment_method:'card',user:{tg_id:123},contact_name:'QA',created_at:'2026-10-15T07:00:00Z' }
const thread = { id:1,user_id:1,status:'open',user:{first_name:'Клієнт QA',tg_id:123},created_at:'2026-10-15T07:00:00Z' }
const initial = {id:1,text:'Історія',direction:'in',is_read:true,delivered:true,author:'QA',created_at:'2026-10-15T07:00:00Z'}
try {
 for (const width of [1280,390,320]) {
  const context = await browser.newContext({viewport:{width,height:820},isMobile:width<760,hasTouch:width<760})
  const errors = [];context.on('page', page => page.on('pageerror', e => errors.push(e.message)))
  const data = {scope:A,sessionFailure:false,sendFailure:false,hold:null,posts:0,order:[{...initial}],support:[{...initial}]}
  await context.route('**/api/**', async route => {
   const path = new URL(route.request().url()).pathname, method = route.request().method()
   let json = {}
   if (path === '/api/auth/session') {
    if(data.sessionFailure) return route.fulfill({status:503,json:{detail:'Тестовий збій сесії'}})
    if(!data.scope) return route.fulfill({status:401,json:{detail:'Сесію завершено'}})
    json = {role:'admin',name:'Однакове ім’я',csrf_token:'csrf-never-persist',draft_scope:data.scope}
   } else if(path === '/api/auth/logout') { data.scope=null; return route.fulfill({status:204}) }
   else if(path === '/api/auth/browser-login') json = {role:'admin',name:'Однакове ім’я',csrf_token:'csrf-never-persist',draft_scope:data.scope || A}
   else if(path === '/api/health') json = {status:'ok'}
   else if(path === '/api/orders/7') json = order
   else if(path === '/api/support') json = [thread]
   else if(path === '/api/support/1') json = thread
   else if(path === '/api/support/stats') json = {open:1,closed:0,total:1,clients:1,unread:0}
   else if(path.endsWith('/messages/read')) json = {marked:0}
   else if(/\/(orders\/7|support\/1)\/messages$/.test(path)) {
    const items = path.includes('/orders/') ? data.order : data.support
    if(method === 'POST') {
     data.posts++
     if(data.sendFailure) return route.fulfill({status:503,json:{detail:'Надсилання тимчасово недоступне'}})
     if(data.hold) await data.hold
     const sent = {...initial,id:items.at(-1).id+1,text:route.request().postDataJSON().text,direction:'out'}
     items.push(sent);json={message:sent,delivered:true}
    } else json = items
   } else if(path.includes('salesdrive-statuses')) json = {statuses:[]}
   else if(path.includes('badges')) json = {orders_new:0,support_unread:0}
   else if(path.includes('notifications')) json = {items:[],unread:0}
   await route.fulfill({json})
  })
  let page = await context.newPage()
  const pathFor = kind => kind === 'order' ? '/orders/7#chat' : '/support?thread=1'
  const compose = (page,kind) => page.locator(kind === 'order' ? '.order-chat-card textarea' : '.support-compose textarea')
  const send = (page,kind) => page.locator(kind === 'order' ? '.order-chat-card' : '.support-conversation').getByRole('button',{name:'Надіслати',exact:true})
  const open = async(page,kind) => { await page.goto(base+pathFor(kind)); await compose(page,kind).waitFor() }
  for(const kind of ['order','support']) {
   const label=width+'/'+kind, draft='Чернетка <b> & 😀 '+label+'\nДругий рядок'
   await open(page,kind);await compose(page,kind).fill(draft)
   await until(async()=>await page.getByText('Чернетка збережена на цьому пристрої',{exact:true}).isVisible())
   check(await compose(page,kind).inputValue()===draft,label+': persisted draft remains editable')
   await page.reload();await compose(page,kind).waitFor()
   check(await compose(page,kind).inputValue()===draft,label+': reload restores full text')
   await page.close();page=await context.newPage();await open(page,kind)
   check(await compose(page,kind).inputValue()===draft,label+': closed and reopened tab restores draft')
   data.sendFailure=true;await send(page,kind).click()
   await page.getByText('Надсилання тимчасово недоступне',{exact:true}).waitFor()
   await page.reload();await compose(page,kind).waitFor()
   check(await compose(page,kind).inputValue()===draft,label+': failed send survives reload')
   data.sendFailure=false
   let release;data.hold=new Promise(resolve=>{release=resolve});const before=data.posts
   await send(page,kind).click();await until(()=>data.posts>before)
   await compose(page,kind).fill('Наступний текст '+label)
   data.hold=null;release();await until(async()=>await send(page,kind).isEnabled())
   check(await compose(page,kind).inputValue()==='Наступний текст '+label,label+': late acknowledgement keeps newer edit')
   await page.reload();await compose(page,kind).waitFor()
   check(await compose(page,kind).inputValue()==='Наступний текст '+label,label+': newer edit persists after acknowledgement')
   await send(page,kind).click();await until(async()=>await compose(page,kind).inputValue()==='')
   await page.reload();await compose(page,kind).waitFor()
   check(await compose(page,kind).inputValue()==='',label+': successfully sent draft never resurrects')
   await compose(page,kind).fill('Окрема чернетка '+label)
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),label+': no horizontal overflow')
  }
  await open(page,'order')
  check(await compose(page,'order').inputValue()==='Окрема чернетка '+width+'/order',width+': support draft does not overwrite order')
  const second=await context.newPage();await open(second,'order')
  await compose(second,'order').fill('Редагування з другої вкладки')
  await until(async()=>await compose(page,'order').inputValue()==='Редагування з другої вкладки')
  check(await compose(page,'order').inputValue()==='Редагування з другої вкладки',width+': same-chat tabs synchronize edits')
  let release;data.hold=new Promise(resolve=>{release=resolve});const before=data.posts
  await send(page,'order').click();await until(()=>data.posts>before)
  await compose(second,'order').fill('Новий текст під час надсилання в іншій вкладці')
  data.hold=null;release();await until(async()=>await send(page,'order').isEnabled())
  check(await compose(second,'order').inputValue()==='Новий текст під час надсилання в іншій вкладці',width+': cross-tab send cannot erase newer draft')
  await second.close()
  // A temporary authentication outage must not delete persisted work.
  data.sessionFailure=true;await page.reload()
  await page.getByRole('button',{name:'Повторити',exact:true}).waitFor()
  check(await page.locator('textarea').count()===0,width+': failed auth check does not expose drafts')
  data.sessionFailure=false;await page.getByRole('button',{name:'Повторити',exact:true}).click()
  await compose(page,'order').waitFor()
  check(await compose(page,'order').inputValue()==='Новий текст під час надсилання в іншій вкладці',width+': auth retry restores work')
  const saved=await page.evaluate(prefix=>Object.fromEntries(Object.entries(localStorage).filter(([k])=>k.startsWith(prefix))),prefix)
  check(!JSON.stringify(saved).includes('csrf-never-persist'),width+': stored drafts contain no authentication or CSRF token')
  // Same display name is deliberately used for two different account scopes.
  data.scope=B;await page.reload();await compose(page,'order').waitFor()
  check(await compose(page,'order').inputValue()==='',width+': different account with same name gets no previous draft')
  await compose(page,'order').fill('Чернетка іншого менеджера')
  data.scope=A;await page.reload();await compose(page,'order').waitFor()
  check(await compose(page,'order').inputValue()==='',width+': switching back cannot recover purged account draft')
  await compose(page,'order').fill('Видалити при виході')
  const logoutTab=await context.newPage();await open(logoutTab,'order')
  if(width<760) await page.getByRole('button',{name:'Відкрити меню',exact:true}).click()
  await page.getByRole('button',{name:'Вийти',exact:true}).first().click()
  await page.waitForURL('**/login')
  await until(async()=>await logoutTab.evaluate(prefix=>!Object.keys(localStorage).some(k=>k.startsWith(prefix)&&!k.endsWith(':active')) ,prefix))
  check(await logoutTab.evaluate(prefix=>!Object.keys(localStorage).some(k=>k.startsWith(prefix)&&!k.endsWith(':active')),prefix),width+': logout removes persisted drafts across tabs')
  if(await compose(logoutTab,'order').count()) {
   await until(async()=>await compose(logoutTab,'order').inputValue()==='')
   await compose(logoutTab,'order').fill('Запізнілий запис')
   check(await compose(logoutTab,'order').inputValue()==='',width+': logged-out tab cannot resurrect draft')
  }
  await logoutTab.close()
  data.scope=A;await open(page,'order');await compose(page,'order').fill('Видалити при 401')
  data.scope=null;await page.reload();await page.getByRole('button',{name:'Увійти',exact:true}).waitFor()
  data.scope=A;await open(page,'order')
  check(await compose(page,'order').inputValue()==='',width+': expired session clears persisted drafts')
  // Browser storage can be unavailable; keep the form usable and tell staff.
  await page.evaluate(prefix=>{const original=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k.startsWith(prefix))throw new DOMException('quota','QuotaExceededError');return original.call(this,k,v)}},prefix)
  await compose(page,'order').fill('Текст тільки у вкладці')
  await page.getByText('Чернетка лише у цій вкладці',{exact:true}).waitFor()
  check(await compose(page,'order').inputValue()==='Текст тільки у вкладці',width+': storage failure retains editable text and visible status')
  check(errors.length===0,width+': no React runtime errors: '+errors.join('; '))
  await context.close()
 }
} finally { await browser.close() }
console.log(`CHAT DRAFT BROWSER: ${checks}/${checks}`)
