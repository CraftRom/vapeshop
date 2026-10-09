import {readFileSync, mkdirSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {join} from 'node:path'
import {chromium} from 'playwright'
const outputDir = process.env.QA_OUTPUT_DIR || fileURLToPath(new URL('./output/', import.meta.url))
mkdirSync(outputDir, {recursive:true})
const browser=await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? {executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH,args:['--no-sandbox']} : {})})
const failures=[];let checks=0
const check=(ok,label)=>{checks++; console.log(`${ok?'PASS':'FAIL'} ${label}`);if(!ok)failures.push(label)}
try {
  let settings=JSON.parse(readFileSync(new URL('./settings-fixture.json',import.meta.url)))
  const updates=[]
  const page=await browser.newPage({viewport:{width:1280,height:600}})
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.addInitScript(()=>{sessionStorage.setItem('shop_dashboard_token','qa');sessionStorage.setItem('shop_dashboard_session',JSON.stringify({role:'admin',name:'QA'}))})
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname
    let data={}
    if(path==='/api/auth/session') data={role:'admin',name:'QA',csrf_token:'qa-csrf'}
    else if(path==='/api/settings') {
      if(route.request().method()==='PUT'){const body=route.request().postDataJSON();updates.push(body);settings={...settings,...body}}
      data=settings
    } else if(path.includes('notifications')) data={items:[],unread:0}
    else if(path.includes('badges')) data={orders_new:0,support_unread:0}
    else if(path.includes('dictionaries')) data={statuses:[],payments:[],deliveries:[]}
    else if(path.includes('environment')) data={items:[]}
    await route.fulfill({json:data})
  })
  await page.goto((process.env.DASHBOARD_URL || 'http://127.0.0.1:5173')+'/settings');await page.getByRole('heading',{name:'Налаштування',exact:true}).waitFor()
  const nav=page.locator('#main-navigation')
  check(await nav.evaluate(e=>e.scrollHeight>e.clientHeight), 'desktop sidebar is scrollable at short height')
  await nav.hover();await page.mouse.wheel(0,480)
  await nav.page().waitForFunction(()=>document.querySelector('#main-navigation').scrollTop>0)
  check(await nav.evaluate(e=>e.scrollTop>0), 'desktop sidebar wheel reaches lower items')
  await page.getByRole('button',{name:'Автовідповіді',exact:true}).click()
  await page.getByRole('switch',{name:'Автовідповіді',exact:true}).uncheck()
  check(await page.getByRole('switch',{name:'Приватні повідомлення',exact:true}).isDisabled(),'master disables scope controls')
  await page.getByRole('region',{name:'Збереження налаштувань'}).getByRole('button',{name:'Зберегти',exact:true}).click()
  await page.getByText('Усі зміни збережено',{exact:true}).waitFor()
  check(updates.length===1 && Object.keys(updates[0]).length===1 && updates[0].auto_replies_enabled===false, 'settings sends only the changed master switch')
  await page.getByRole('searchbox',{name:'Пошук налаштувань'}).fill('телефон')
  check(await page.getByRole('heading',{name:'Реквізити продавця',exact:true}).isVisible(), 'settings search finds fields across categories')
  await page.getByRole('searchbox').fill('')
  await page.screenshot({path:join(outputDir,'settings-desktop.png'),fullPage:true})
  await page.setViewportSize({width:360,height:420})
  await page.getByRole('button',{name:'Відкрити меню',exact:true}).click()
  check(await nav.evaluate(e=>e.scrollHeight>e.clientHeight), 'mobile menu owns a bounded scroll area')
  await nav.hover();await page.mouse.wheel(0,450)
  await nav.page().waitForFunction(()=>document.querySelector('#main-navigation').scrollTop>0)
  check(await nav.evaluate(e=>e.scrollTop>0), 'mobile menu reaches the last routes')
  await page.getByRole('button',{name:'Закрити меню',exact:true}).click()
  const tabs=page.locator('.settings-tabs');await tabs.hover();await page.mouse.wheel(0,200)
  await page.waitForFunction(()=>document.querySelector('.settings-tabs').scrollLeft>0)
  check(await tabs.evaluate(e=>e.scrollLeft>0), 'settings categories scroll with the mouse wheel')
  await page.screenshot({path:join(outputDir,'settings-mobile.png'),fullPage:true})
  check(!errors.length,'dashboard has no runtime errors: '+errors.join('; '))
  await page.close()

  for(const viewport of [{width:900,height:560},{width:360,height:640}]) {
    const p=await browser.newPage({viewport})
    let failProducts=false
    const errors=[];p.on('pageerror',e=>errors.push(e.message))
    await p.addInitScript(()=>{window.Telegram={WebApp:{initData:'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test',platform:'tdesktop',initDataUnsafe:{user:{id:123}},ready(){},expand(){},disableVerticalSwipes(){},onEvent(){},offEvent(){}}}})
    await p.route('**/api/**', async route=>{
      const path=new URL(route.request().url()).pathname
      if(path.endsWith('/products') && failProducts){await route.fulfill({status:503,json:{detail:'QA unavailable'}});return}
      let data=[]
      if(path.endsWith('/config'))data={age_confirmed:true,min_age:18,shop_name:'QA',currency:'грн',bonus_enabled:false,referral_enabled:false}
      else if(path.endsWith('/cart'))data={lines:[],subtotal:'0'}
      else if(path.endsWith('/profile'))data={first_name:'QA',bonus_balance:'0',orders_count:0}
      else if(path.endsWith('/categories'))data=Array.from({length:18},(_,i)=>({id:i+1,name:`Категорія ${i+1}`}))
      else if(path.endsWith('/products'))data=Array.from({length:12},(_,i)=>({id:i+1,name:`Товар ${i+1}`,stock:5,price:'100',category_id:1}))
      else if(path.endsWith('/wishlists'))data=Array.from({length:25},(_,i)=>({id:i+1,name:`Список ${i+1}`,product_ids:[],size:0}))
      await route.fulfill({json:data})
    })
    await p.goto((process.env.MINIAPP_URL || 'http://127.0.0.1:5174')+'/app/')
    const rails=p.locator('.rail');await rails.first().waitFor()
    check(await p.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),`${viewport.width}px storefront has no page-wide horizontal overflow`)
    await rails.first().hover()
    // Wheel dispatch is asynchronous in headless Chromium; wait for each attempt.
    for (let attempt = 0; attempt < 3; attempt++) {
      await p.mouse.wheel(0,300)
      try { await p.waitForFunction(()=>document.querySelector('.rail').scrollLeft>0, null, {timeout:1500}); break } catch (error) { if (attempt === 2) throw error }
    }
    check(await rails.first().evaluate(e=>e.scrollLeft>0),`${viewport.width}px catalog categories scroll by wheel`)
    await rails.nth(1).hover();await p.mouse.wheel(0,200)
    check(await rails.nth(1).evaluate(e=>e.scrollWidth<=e.clientWidth || e.scrollLeft>0),`${viewport.width}px filters scroll when overflowing`)
    await p.getByRole('button',{name:/^Сортування:/}).click()
    await p.getByRole('button',{name:'За порядком',exact:true}).click()
    const save=p.getByRole('button',{name:'Відкласти'}).first();await save.click()
    const sheet=p.getByRole('dialog',{name:'Зберегти в список'});await sheet.waitFor()
    check(await sheet.evaluate(e=>e.scrollHeight>e.clientHeight), `${viewport.width}px long wishlist menu scrolls`)
    const buttons=sheet.getByRole('button');await buttons.last().focus();await p.keyboard.press('Tab')
    check(await buttons.first().evaluate(e=>e===document.activeElement),`${viewport.width}px dialog keeps keyboard focus inside`)
    check(await p.evaluate(()=>document.body.style.overflow==='hidden'),`${viewport.width}px sheet locks background scroll`)
    await sheet.hover();await p.mouse.wheel(0,800)
    await p.waitForFunction(()=>document.querySelector('.sheet').scrollTop>0)
    check(await sheet.evaluate(e=>e.scrollTop>0),`${viewport.width}px wishlist wheel reaches lower lists`)
    await p.screenshot({path:join(outputDir,`storefront-${viewport.width}.png`)})
    await p.keyboard.press('Escape')
    check(await sheet.count()===0,`${viewport.width}px Escape closes the sheet`)
    check(await p.evaluate(()=>document.body.style.overflow!=='hidden'),`${viewport.width}px closing restores document scroll`)
    failProducts=true
    await p.getByRole('button',{name:'Категорія 1',exact:true}).click()
    await p.getByRole('heading',{name:'Не вдалося завантажити каталог'}).waitFor()
    check(await p.locator('.skeleton').count()===0,`${viewport.width}px failed catalog request ends loading`)
    failProducts=false
    await p.getByRole('button',{name:'Повторити',exact:true}).click()
    await p.getByRole('button',{name:'Відкласти'}).first().waitFor()
    check(await p.getByRole('heading',{name:'Не вдалося завантажити каталог'}).count()===0,`${viewport.width}px catalog retry recovers after network failure`)
    check(!errors.length,`${viewport.width}px storefront has no runtime errors: ${errors.join('; ')}`)
    await p.close()
  }
}finally{await browser.close()}
console.log(`BROWSER: ${checks-failures.length}/${checks}`)
if(failures.length)process.exitCode=1
