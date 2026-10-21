import assert from 'node:assert/strict'
import {chromium} from 'playwright'
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH,args:['--no-sandbox','--disable-dev-shm-usage']})
let checks=0
const check=(ok,label)=>{assert.ok(ok,label);checks++;console.log('PASS '+label)}
const wait=ms=>new Promise(r=>setTimeout(r,ms))
const until=async fn=>{for(let i=0;i<150;i++){if(await fn())return;await wait(40)}throw Error('Condition timed out')}
try {
 for(const width of [320,390,1280]){
  const page=await browser.newPage({viewport:{width,height:850},isMobile:width<760,hasTouch:width<760});page.setDefaultTimeout(12000)
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  const good=()=>({product_id:1,name:'Доступний товар',price:'19.90',qty:2,stock:50,is_available:true,line_total:'39.80'})
  const bad=()=>({product_id:2,name:'Недоступний товар',price:'9.50',qty:2,stock:20,is_available:false,line_total:'19.00'})
  const state={lines:[good(),bad()],events:[],hold:null,fail:false,deleteHold:null,getHold:null,heldRead:false,failIds:new Set()}
  const cart=()=>({lines:state.lines.map(x=>({...x,line_total:(Number(x.price)*x.qty).toFixed(2)})),subtotal:state.lines.reduce((s,x)=>s+Number(x.price)*x.qty,0).toFixed(2),problems:state.lines.filter(x=>!x.is_available).map(x=>'«'+x.name+'» більше недоступний')})
  await page.addInitScript(()=>{window.__popupCalls=0;window.Telegram={WebApp:{initData:'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test',initDataUnsafe:{user:{id:123}},platform:'tdesktop',ready(){},expand(){},onEvent(){},offEvent(){},showConfirm(){window.__popupCalls++;throw Error('WebAppMethodUnsupported')},BackButton:{show(){},hide(){},onClick(){},offClick(){}}}}})
  await page.route('https://telegram.org/**',r=>r.fulfill({body:''}))
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();let json=[]
   if(path.endsWith('/config'))json={age_confirmed:true,currency:'грн',bonus_enabled:false,referral_enabled:false,payment_methods:[],delivery_methods:[]}
   else if(path.endsWith('/profile'))json={first_name:'QA',orders_count:0,bonus_balance:'0'}
   else if(path.endsWith('/orders'))json={items:[],has_more:false,total:0}
   else if(path.endsWith('/cart') || /\/cart\/\d+$/.test(path)){
    if(method==='POST'){
     const body=route.request().postDataJSON();state.events.push('POST-start:'+body.product_id)
     if(state.hold)await state.hold
     const item=state.lines.find(x=>x.product_id===body.product_id)
     if(item)item.qty=Math.max(0,item.qty+body.delta)
     state.lines=state.lines.filter(x=>x.qty>0);state.events.push('POST-end:'+body.product_id)
    }else if(method==='DELETE'){
     state.events.push('DELETE:'+path)
     if(state.deleteHold)await state.deleteHold
     if(state.fail || state.failIds.has(+path.split('/').at(-1)))return route.fulfill({status:503,json:{detail:'Кошик тимчасово недоступний'}})
     if(path.endsWith('/cart'))state.lines=[]
     else state.lines=state.lines.filter(x=>x.product_id!==+path.split('/').at(-1))
    }
    json=cart()
    if(method==='GET' && state.getHold){const hold=state.getHold;state.getHold=null;state.heldRead=true;await hold}
   }
   return route.fulfill({json})
  })
  const open=async()=>{await page.goto((process.env.MINIAPP_URL||'http://127.0.0.1:5174')+'/app/');try{await page.getByRole('navigation').getByRole('button',{name:'Кошик',exact:true}).click()}catch(e){console.log('OPEN DIAGNOSTIC',width,errors,await page.locator('body').innerText());throw e};await page.getByRole('heading',{name:'Кошик',exact:true}).waitFor()}
  const card=name=>page.locator('.cart-list .card').filter({has:page.getByText(name,{exact:true})})
  await open()
  check(await card('Недоступний товар').getByRole('button',{name:'Додати одну'}).isDisabled(),width+': unavailable product cannot be increased')
  await card('Недоступний товар').getByRole('button',{name:'Прибрати одну'}).click();await until(()=>state.lines.find(x=>x.product_id===2)?.qty===1)
  check(true,width+': minus request still works for inactive product')
  await page.getByRole('button',{name:'Видалити Недоступний товар з кошика',exact:true}).click();await until(()=>state.lines.length===1)
  check(state.lines[0].product_id===1 && state.events.some(x=>x==='DELETE:/api/shop/cart/2'),width+': explicit removal deletes only selected product')
  await until(()=>page.locator('[data-cart-remove=\"1\"]').evaluate(el=>el===document.activeElement))
  check(true,width+': keyboard focus moves to the next remaining product')
  await page.getByRole('button',{name:'Очистити кошик',exact:true}).click()
  check(await page.getByRole('group',{name:'Підтвердження очищення кошика'}).isVisible(),width+': clear confirmation rendered inside application')
  const deletes=state.events.filter(x=>x.startsWith('DELETE:')).length
  await page.getByRole('button',{name:'Залишити товари',exact:true}).click()
  check(state.lines.length===1 && state.events.filter(x=>x.startsWith('DELETE:')).length===deletes,width+': cancelling clear does not mutate cart')
  await page.getByRole('button',{name:'Очистити кошик',exact:true}).click();await page.getByRole('button',{name:'Так, очистити',exact:true}).click()
  await page.getByRole('heading',{name:'Кошик поки порожній',exact:true}).waitFor()
  check(state.lines.length===0 && await page.evaluate(()=>window.__popupCalls)===0,width+': clear succeeds despite broken Telegram popup API')
  state.lines=[good(),{...bad(),qty:120}];await open()
  state.fail=true;const attempts=state.events.length
  await page.getByRole('button',{name:'Видалити Недоступний товар з кошика',exact:true}).click()
  await card('Недоступний товар').getByRole('alert').getByText('Кошик тимчасово недоступний',{exact:true}).waitFor()
  check(state.lines.find(x=>x.product_id===2)?.qty===120 && await card('Недоступний товар').count()===1,width+': failure retains unavailable product and shows visible error')
  check(state.events.length===attempts+1,width+': failed DELETE is not silently retried')
  state.fail=false;await card('Недоступний товар').getByRole('button',{name:'Повторити видалення',exact:true}).click();await until(()=>state.lines.length===1)
  check(true,width+': whole-line deletion handles quantity above delta limit')
  let release;state.hold=new Promise(r=>{release=r});const start=state.events.length
  await card('Доступний товар').getByRole('button',{name:'Додати одну'}).click();await until(()=>state.events.slice(start).includes('POST-start:1'))
  await page.getByRole('button',{name:'Очистити кошик',exact:true}).click();await page.getByRole('button',{name:'Так, очистити',exact:true}).click();await wait(100)
  check(!state.events.slice(start).some(x=>x.startsWith('DELETE:')),width+': clear waits for earlier in-flight quantity update')
  state.hold=null;release();await page.getByRole('heading',{name:'Кошик поки порожній',exact:true}).waitFor();await wait(450)
  check(state.lines.length===0 && state.events.slice(start).join('|')==='POST-start:1|POST-end:1|DELETE:/api/shop/cart',width+': delayed plus cannot resurrect cleared cart')
  state.lines=[good(),bad()];await open();const before=state.events.length
  await card('Доступний товар').getByRole('button',{name:'Додати одну'}).click()
  await page.getByRole('button',{name:'Видалити Недоступний товар з кошика',exact:true}).click();await until(()=>state.lines.length===1 && state.lines[0].qty===3)
  check(state.events.slice(before).join('|')==='POST-start:1|POST-end:1|DELETE:/api/shop/cart/2',width+': row deletion preserves another product pending changes')
  // Two independent row buttons remain usable; repeated taps on one row are ignored.
  state.lines=[good(),bad()];await open();let releaseDelete;state.deleteHold=new Promise(r=>{releaseDelete=r});const beforeDeletes=state.events.length
  const badRemove=page.getByRole('button',{name:'Видалити Недоступний товар з кошика',exact:true})
  await badRemove.evaluate(el=>{el.click();el.click()});await until(()=>state.events.length>beforeDeletes)
  check(await badRemove.isDisabled() && (await badRemove.innerText()).includes('Видаляємо'),width+': selected row has its own pending state')
  check(await card('Доступний товар').getByRole('button',{name:'Додати одну'}).isEnabled() && await page.getByRole('button',{name:'Видалити Доступний товар з кошика',exact:true}).isEnabled(),width+': other product remains usable during deletion')
  check(await page.getByRole('button',{name:'Очистити кошик',exact:true}).isDisabled(),width+': clear waits while individual deletions are pending')
  await page.getByRole('button',{name:'Видалити Доступний товар з кошика',exact:true}).click()
  state.deleteHold=null;releaseDelete();await page.getByRole('heading',{name:'Кошик поки порожній',exact:true}).waitFor()
  check(state.events.slice(beforeDeletes).filter(x=>x.startsWith('DELETE:')).length===2,width+': independent deletions serialize without duplicate requests')
  check(await page.getByRole('status').filter({hasText:'видалено з кошика'}).count()===1,width+': final successful deletion has an accessible result')
  // A stale recovery GET from a failed first deletion cannot undo the second success.
  state.lines=[good(),bad()];state.failIds.add(2);await open();let releaseGet;state.heldRead=false;state.getHold=new Promise(r=>{releaseGet=r})
  await page.getByRole('button',{name:'Видалити Недоступний товар з кошика',exact:true}).click();await until(()=>state.heldRead)
  await page.getByRole('button',{name:'Видалити Доступний товар з кошика',exact:true}).click();await until(()=>!state.lines.some(x=>x.product_id===1))
  releaseGet();await card('Недоступний товар').getByRole('alert').waitFor();await wait(100)
  check(await card('Доступний товар').count()===0 && await card('Недоступний товар').count()===1,width+': stale failed-delete read cannot resurrect another removed product')
  check(await card('Недоступний товар').getByRole('button',{name:'Повторити видалення'}).isEnabled(),width+': retry stays next to the failed product')
  state.failIds.clear();await card('Недоступний товар').getByRole('button',{name:'Повторити видалення'}).click();await page.getByRole('heading',{name:'Кошик поки порожній',exact:true}).waitFor()
  // Long customer-facing names and touch target sizes.
  const longName='Довга назва товару з характеристиками '.repeat(15)
  state.lines=[{...good(),name:longName}];await open()
  const touch=page.locator('[data-cart-remove="1"]'),rect=await touch.boundingBox()
  check(rect.width>=44 && rect.height>=44,width+': deletion has a touch target of at least 44 by 44 px')
  check(await touch.getAttribute('aria-label')==='Видалити '+longName+' з кошика',width+': accessible name identifies the complete product')
  if(width===320)await page.screenshot({path:'qa/output/cart-buttons-320.png',fullPage:true})
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+': no horizontal overflow')
  check(errors.length===0,width+': no unhandled JavaScript errors '+errors.join(';'))
  await page.close()
 }
}finally{await browser.close()}
console.log(`CART RECOVERY BROWSER: ${checks}/${checks}`)
