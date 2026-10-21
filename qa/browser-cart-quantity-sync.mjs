import assert from 'node:assert/strict'
import {chromium} from 'playwright'
import {pageFixture} from './paged-fixture.mjs'
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH,args:['--no-sandbox','--disable-dev-shm-usage']})
let checks=0
const check=(ok,label)=>{assert.ok(ok,label);checks++;console.log('PASS '+label)}
const wait=ms=>new Promise(r=>setTimeout(r,ms))
const until=async fn=>{for(let i=0;i<200;i++){if(await fn())return;await wait(40)}throw Error('Condition timed out')}
try {
 for(const width of [320,390,1280]){
  const page=await browser.newPage({viewport:{width,height:850},isMobile:width<760,hasTouch:width<760});page.setDefaultTimeout(18000)
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  const good=(qty=2,stock=1000)=>({product_id:1,name:'Кількість',price:'19.90',qty,stock,is_available:true,line_total:(19.90*qty).toFixed(2)})
  const state={lines:[good()],posts:[],holds:new Map(),gets:0,failAfter:false,failCall:0,deletes:0,getHoldNext:null}
  const cart=()=>({lines:state.lines.map(x=>({...x,line_total:(+x.price*x.qty).toFixed(2)})),subtotal:state.lines.reduce((s,x)=>s+(+x.price*x.qty),0).toFixed(2),problems:[]})
  await page.addInitScript(()=>{window.Telegram={WebApp:{initData:'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test',initDataUnsafe:{user:{id:123}},platform:'tdesktop',ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}}}}})
  await page.route('https://telegram.org/**',r=>r.fulfill({body:''}))
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();let json=[]
   if(path.endsWith('/config'))json={age_confirmed:true,currency:'грн',bonus_enabled:false,referral_enabled:false,payment_methods:[],delivery_methods:[]}
   else if(path.endsWith('/profile'))json={first_name:'QA',orders_count:0,bonus_balance:'0'}
   else if(path.endsWith('/orders'))json={items:[],has_more:false,total:0}
   else if(path.endsWith('/products'))json=pageFixture(route,[{id:1,name:'Кількість',price:'19.90',stock:1000,is_active:true,category_id:null,subcategory_id:null}])
   else if(path.endsWith('/cart') || /\/cart\/\d+$/.test(path)){
    if(method==='POST'){
     const body=route.request().postDataJSON();state.posts.push(body);const call=state.posts.length
     assert.ok(Math.abs(body.delta)<=99,'API delta limit')
     if(state.holds.has(call))await state.holds.get(call)
     if(state.failCall===call)return route.fulfill({status:503,json:{detail:'Не вдалося зберегти кількість'}})
     const item=state.lines.find(x=>x.product_id===body.product_id)
     if(item)item.qty=Math.min(item.stock,Math.max(0,item.qty+body.delta))
     else if(body.delta>0)state.lines.push(good(body.delta))
     state.lines=state.lines.filter(x=>x.qty>0)
     if(state.failAfter){state.failAfter=false;return route.fulfill({status:503,json:{detail:'Невідомий результат збереження'}})}
    }else if(method==='DELETE'){state.deletes++;state.lines=[]}
    else if(method==='GET'){
     state.gets++;const snapshot=cart();if(state.getHoldNext){const hold=state.getHoldNext;state.getHoldNext=null;await hold};return route.fulfill({json:snapshot})
    }
    json=cart()
   }
   return route.fulfill({json})
  })
  const open=async(q=2,stock=1000)=>{
   state.lines=[good(q,stock)];state.posts=[];state.holds.clear();state.failAfter=false;state.failCall=0
   await page.goto((process.env.MINIAPP_URL||'http://127.0.0.1:5174')+'/app/')
   await page.getByRole('navigation').getByRole('button',{name:'Кошик',exact:true}).click()
   await page.locator('[data-cart-quantity="1"]').waitFor()
  }
  const quantity=()=>page.locator('[data-cart-quantity="1"]')
  const plus=()=>page.getByRole('button',{name:'Додати одну',exact:true})
  const minus=()=>page.getByRole('button',{name:'Прибрати одну',exact:true})
  const saving=()=>page.getByRole('status').filter({hasText:'Зберігаємо кількість'})
  await open();let release1,release2
  state.holds.set(1,new Promise(r=>{release1=r}));state.holds.set(2,new Promise(r=>{release2=r}))
  await plus().click()
  check(await quantity().innerText()==='3',width+': first tap changes visible quantity immediately')
  check(await saving().count()===1,width+': pending quantity has an explicit saving state')
  check((await page.locator('.cart-card .price').innerText()).includes('39,80'),width+': money stays at server-confirmed subtotal before acknowledgement')
  await until(()=>state.posts.length===1)
  await plus().evaluate(el=>{el.click();el.click()})
  check(await quantity().innerText()==='5',width+': taps during first request accumulate immediately')
  release1();await until(()=>state.posts.length===2);await wait(100)
  check(await quantity().innerText()==='5',width+': first acknowledgement cannot erase newer taps or roll quantity back')
  check(await saving().count()===1,width+': saving continues while next batch is pending')
  release2();await until(async()=>await saving().count()===0)
  check(state.lines[0].qty===5 && await quantity().innerText()==='5',width+': server and visible quantity converge after both batches')
  // Net-zero taps must not send a useless delta.
  const before=state.posts.length;await plus().evaluate(el=>el.click());await minus().evaluate(el=>el.click());await wait(500)
  check(state.posts.length===before && await quantity().innerText()==='5',width+': opposite taps cancel before the debounce write')
  await open();await plus().evaluate(el=>{for(let i=0;i<120;i++)el.click()})
  check(await quantity().innerText()==='122',width+': rapid large batch preserves all requested taps')
  await until(async()=>await saving().count()===0)
  check(state.posts.map(x=>x.delta).join(',')==='99,21' && state.lines[0].qty===122,width+': large batch respects the API limit without losing quantity')
  await open(2,4);await plus().evaluate(el=>{for(let i=0;i<10;i++)el.click()})
  check(await quantity().innerText()==='4' && await plus().isDisabled(),width+': rapid taps cannot exceed known stock')
  await until(async()=>await saving().count()===0)
  check(state.lines[0].qty===4 && state.posts.reduce((s,x)=>s+x.delta,0)===2,width+': only admissible increments reach server')
  // A server commit followed by a lost/error response must never replay POST.
  await open();state.failAfter=true;await plus().click()
  await page.locator('.cart-card .cart-row-error').filter({hasText:'Невідомий результат збереження'}).waitFor()
  check(state.lines[0].qty===3 && await quantity().innerText()==='3' && state.posts.length===1,width+': unknown response displays canonical quantity without duplicate POST')
  const gets=state.gets;await page.getByRole('button',{name:'Оновити кількість',exact:true}).click()
  await until(async()=>await page.locator('.cart-card .cart-row-error').count()===0)
  check(state.gets>gets && state.posts.length===1,width+': explicit quantity recovery performs GET rather than repeating the delta')
  // A slow explicit recovery read must not replace the newer pre-checkout snapshot.
  await open();state.failAfter=true;await plus().click()
  await page.locator('.cart-card .cart-row-error').filter({hasText:'Невідомий результат збереження'}).waitFor()
  let releaseOldGet;state.getHoldNext=new Promise(r=>{releaseOldGet=r});const beforeGet=state.gets
  await page.getByRole('button',{name:'Оновити кількість',exact:true}).click();await until(()=>state.gets>beforeGet)
  state.lines[0].qty=4
  await page.getByRole('button',{name:'Оформити',exact:true}).click()
  await page.getByText('Не всі зміни кошика вдалося зберегти. Перевірте кількість і суму, потім натисніть «Оформити» ще раз.',{exact:true}).waitFor()
  check(await quantity().innerText()==='4',width+': checkout preparation obtains the newer quantity')
  releaseOldGet();await until(async()=>await page.getByRole('button',{name:'Оновлюємо…',exact:true}).count()===0)
  check(await quantity().innerText()==='4',width+': late row recovery cannot replace pre-checkout quantity with an older snapshot')
  // A later chunk may fail after an earlier chunk committed.
  await open();state.failCall=2;await plus().evaluate(el=>{for(let i=0;i<120;i++)el.click()})
  await page.locator('.cart-card .cart-row-error').filter({hasText:'Не вдалося зберегти кількість'}).waitFor()
  check(state.lines[0].qty===101 && await quantity().innerText()==='101' && state.posts.length===2,width+': partial chunk failure shows actual persisted quantity')
  state.failCall=0;await plus().click();await until(async()=>await saving().count()===0)
  check(state.lines[0].qty===102 && state.posts.at(-1).delta===1,width+': next explicit tap does not replay failed batch remainder')
  // Removing/clearing cancels the old pending epoch; a later addition is independent.
  for(const mode of ['clear','remove']){
   await open();let release;state.holds.set(1,new Promise(r=>{release=r}));await plus().click();await until(()=>state.posts.length===1)
   if(mode==='clear'){
    await page.getByRole('button',{name:'Очистити кошик',exact:true}).click();await page.getByRole('button',{name:'Так, очистити',exact:true}).click()
   }else await page.getByRole('button',{name:'Видалити Кількість з кошика',exact:true}).click()
   release();await page.getByRole('heading',{name:'Кошик поки порожній',exact:true}).waitFor()
   await page.getByRole('button',{name:'До каталогу',exact:true}).click()
   await page.getByRole('button',{name:'Додати в кошик: Кількість',exact:true}).click()
   await until(()=>state.lines[0]?.qty===1)
   await page.getByRole('navigation').getByRole('button',{name:'Кошик',exact:true}).click();await quantity().waitFor()
   check(await quantity().innerText()==='1' && await saving().count()===0,width+': '+mode+' discards old acknowledgements without affecting a later addition')
  }
  await open();await minus().evaluate(el=>{for(let i=0;i<10;i++)el.click()})
  check(await quantity().innerText()==='0' && await minus().isDisabled(),width+': rapid decrement cannot show negative quantity')
  await page.getByRole('heading',{name:'Кошик поки порожній',exact:true}).waitFor()
  check(state.posts.reduce((s,x)=>s+x.delta,0)===-2,width+': decrement removes only the existing quantity')
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+': no horizontal overflow')
  check(errors.length===0,width+': no React errors '+errors.join(';'))
  await page.close()
 }
}finally{await browser.close()}
console.log(`CART QUANTITY SYNC BROWSER: ${checks}/${checks}`)
