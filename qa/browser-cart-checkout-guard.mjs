import assert from 'node:assert/strict'
import {chromium} from 'playwright'
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH,args:['--no-sandbox','--disable-dev-shm-usage']})
let checks=0
const check=(ok,label)=>{assert.ok(ok,label);checks++;console.log('PASS '+label)}
const wait=ms=>new Promise(r=>setTimeout(r,ms))
const until=async fn=>{for(let i=0;i<200;i++){if(await fn())return;await wait(40)}throw Error('Condition timed out')}
try {
 for(const width of [320,390,1280]){
  const page=await browser.newPage({viewport:{width,height:850},isMobile:width<760,hasTouch:width<760});page.setDefaultTimeout(18000)
  const errors=[],diagnostic=[];page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>diagnostic.push(r.url()+': '+r.failure()?.errorText));page.on('console',m=>{if(m.type()==='error')diagnostic.push(m.text())})
  const good=()=>({product_id:1,name:'Товар для перевірки',price:'19.90',qty:2,stock:50,is_available:true,line_total:'39.80'})
  const state={lines:[good()],problems:[],failPost:false,postHold:null,getHold:null,failGet:false,reads:0,posts:0,quoteCalls:0}
  const cart=()=>({lines:state.lines.map(x=>({...x,line_total:(+x.price*x.qty).toFixed(2)})),subtotal:state.lines.reduce((s,x)=>s+(+x.price*x.qty),0).toFixed(2),problems:state.problems})
  await page.addInitScript(()=>{window.Telegram={WebApp:{initData:'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test',initDataUnsafe:{user:{id:123}},platform:'tdesktop',ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}}}}})
  await page.route('https://telegram.org/**',r=>r.fulfill({body:''}))
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();let json=[]
   if(path.endsWith('/config'))json={age_confirmed:true,currency:'грн',bonus_enabled:false,referral_enabled:false,payment_methods:[],delivery_methods:[]}
   else if(path.endsWith('/profile'))json={first_name:'QA',orders_count:0,bonus_balance:'0'}
   else if(path.endsWith('/orders'))json={items:[],has_more:false,total:0}
   else if(path.endsWith('/cart')){
    if(method==='POST'){
     state.posts++;const body=route.request().postDataJSON();if(state.postHold)await state.postHold
     if(state.failPost)return route.fulfill({status:503,json:{detail:'Не вдалося зберегти кількість'}})
     const item=state.lines.find(x=>x.product_id===body.product_id);if(item)item.qty=Math.max(0,item.qty+body.delta)
     state.lines=state.lines.filter(x=>x.qty>0)
    }else if(method==='GET'){
     state.reads++;if(state.getHold)await state.getHold
     if(state.failGet)return route.fulfill({status:503,json:{detail:'Кошик тимчасово недоступний'}})
    }
    json=cart()
   }else if(path.endsWith('/checkout/quote')){
    state.quoteCalls++;const sum=cart().subtotal;json={subtotal:sum,discount:'0',bonus_available:'0',bonus_used:'0',total:sum,quote_token:'a'.repeat(64)}
   }
   await route.fulfill({json})
  })
  const open=async()=>{await page.goto((process.env.MINIAPP_URL||'http://127.0.0.1:5174')+'/app/');try{await page.getByRole('navigation').getByRole('button',{name:'Кошик',exact:true}).click()}catch(e){console.log('OPEN DIAGNOSTIC',width,errors,diagnostic,await page.locator('body').innerText());throw e};await page.getByRole('heading',{name:'Кошик',exact:true}).waitFor()}
  const checkout=()=>page.getByRole('button',{name:'Оформити',exact:true})
  const form=()=>page.getByRole('heading',{name:'Оформлення',exact:true})
  // Failed quantity write must require review instead of silently opening checkout.
  await open();state.failPost=true;let releasePost;state.postHold=new Promise(r=>{releasePost=r})
  await page.getByRole('button',{name:'Додати одну'}).click();await until(()=>state.posts===1)
  await checkout().click();check(await page.getByRole('button',{name:'Перевіряємо…',exact:true}).isDisabled(),width+': checkout has an immediate pending state')
  check(await page.getByRole('button',{name:'Додати одну'}).isDisabled(),width+': quantity controls lock during checkout preparation')
  state.postHold=null;releasePost()
  await page.getByText('Не всі зміни кошика вдалося зберегти. Перевірте кількість і суму, потім натисніть «Оформити» ще раз.',{exact:true}).waitFor()
  check(await form().count()===0 && state.quoteCalls===0,width+': failed pending write cannot enter checkout')
  check(state.lines[0].qty===2 && state.posts===1,width+': failed delta is not repeated automatically')
  state.failPost=false;await checkout().click();await form().waitFor();check(true,width+': explicit retry after reviewing canonical cart can proceed')
  // A stock change after initial load is discovered by a fresh read.
  state.lines=[good()];state.problems=[];await open();state.lines[0].stock=1;state.problems=['У кошику 2, доступно 1']
  const beforeQuotes=state.quoteCalls,beforeReads=state.reads
  await checkout().click();await page.getByText('Доступно лише 1 шт. Зменште кількість.',{exact:true}).waitFor()
  check(state.reads>beforeReads && state.quoteCalls===beforeQuotes && await form().count()===0,width+': latest stock blocks checkout and identifies the affected line')
  check(await page.getByRole('button',{name:'Прибрати одну'}).isEnabled() && await page.getByRole('button',{name:'Додати одну'}).isDisabled(),width+': shortage keeps correction/removal available and blocks increase')
  state.lines=[{...good(),stock:0,is_available:false}];state.problems=['Немає в наявності'];await open()
  check(await page.getByText('Немає в наявності',{exact:true}).count()===1,width+': zero-stock item has a local availability explanation')
  state.lines=[{...good(),is_available:false}];state.problems=['Недоступний'];await open()
  check(await page.getByText('Товар недоступний',{exact:true}).count()===1,width+': inactive item is distinguished from zero stock')
  // A failure to read the canonical cart keeps the existing data visible.
  state.lines=[good()];state.problems=[];await open();state.failGet=true;await checkout().click()
  await page.getByRole('alert').filter({hasText:'Кошик тимчасово недоступний'}).waitFor()
  check(await form().count()===0 && await page.getByText('Товар для перевірки',{exact:true}).count()===1,width+': unavailable canonical read cannot open checkout or erase visible cart')
  state.failGet=false
  // Empty canonical state (for example, cleared in the bot) must not use a stale render.
  state.lines=[good()];await open();state.lines=[];await checkout().click()
  await page.getByRole('heading',{name:'Кошик поки порожній',exact:true}).waitFor()
  check(await form().count()===0,width+': cart cleared elsewhere cannot open a stale checkout')
  await page.getByRole('button',{name:'До каталогу',exact:true}).click()
  check(await page.getByRole('heading',{name:'Кошик поки порожній',exact:true}).count()===0,width+': empty cart offers a working return to catalog')
  // Navigation cancels the pending preparation, so a late GET cannot open the form.
  state.lines=[good()];await open();let releaseGet;state.getHold=new Promise(r=>{releaseGet=r});const pre=state.reads
  await checkout().click();await until(()=>state.reads>pre)
  await page.getByRole('navigation').getByRole('button',{name:'Чат',exact:true}).click()
  state.getHold=null;releaseGet();await wait(150)
  check(await form().count()===0 && await page.getByRole('button',{name:'Загальна підтримка',exact:true}).isVisible(),width+': late cart response respects navigation away')
  // Double taps produce one canonical check.
  state.lines=[good()];await open();let releaseDouble;state.getHold=new Promise(r=>{releaseDouble=r});const reads=state.reads
  await checkout().evaluate(el=>{el.click();el.click()});await until(()=>state.reads>reads)
  check(state.reads===reads+1,width+': double click starts a single canonical check')
  state.getHold=null;releaseDouble();await form().waitFor()
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+': no horizontal overflow')
  check(errors.length===0,width+': no React errors '+errors.join(';'))
  await page.close()
 }
}finally{await browser.close()}
console.log(`CART CHECKOUT GUARD BROWSER: ${checks}/${checks}`)
