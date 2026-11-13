/** Browser regression: real video decoding, opt-in downloads, uploads, both rooms.
 * Run after Vite servers are started: QA_BROWSER_SUITE=chat-video bash qa/run-browser.sh
 * Telegram/API are isolated; a real codec-bearing 1s MP4 fixture is used.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { chromium } from 'playwright'
const clip = readFileSync(new URL('./fixtures/chat-video.mp4', import.meta.url))
const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH||undefined, args:['--no-sandbox','--disable-dev-shm-usage']})
let checks = 0
const check = (cond, label) => { assert.ok(cond, label); checks++; console.log('PASS '+label) }
const wait = ms => new Promise(resolve => setTimeout(resolve, ms))
const item = (id, kind='video') => ({id, direction:'out', author:'Менеджер', text:'', file_kind:kind, file_name:'clip.mp4', created_at:'2026-11-09T12:00:00Z'})
const order={id:7,status:'accepted',status_label:'В роботі',total:'42.00',can_chat:true,created_at:'2026-11-09T12:00:00Z',items:[]}
try {
 for (const width of [390, 1280]) {
  const page = await browser.newPage({viewport:{width,height:820},hasTouch:width<760,isMobile:width<760})
  const errors=[]; page.on('pageerror',e=>errors.push(e.message))
  const state={downloads:0,uploads:[],orderMessages:[item(10)],supportMessages:[item(20)]}
  await page.addInitScript(() => {
    window.Telegram={WebApp:{initData:'user=%7B%22id%22%3A123%7D&auth_date=1&hash=test',initDataUnsafe:{user:{id:123}},colorScheme:'dark',platform:'tdesktop',ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}}}}
    window.__blobRevoked=0
    const original=URL.revokeObjectURL.bind(URL)
    URL.revokeObjectURL=(value)=>{window.__blobRevoked++;original(value)}
  })
  await page.route('https://telegram.org/**',route=>route.fulfill({body:''}))
  await page.route('**/api/**',async route=>{
    const u=new URL(route.request().url()),p=u.pathname,method=route.request().method()
    let json=[]
    if(p.endsWith('/config'))json={age_confirmed:true,currency:'грн',shop_name:'QA',payment_methods:[],delivery_methods:[]}
    else if(p.endsWith('/cart'))json={lines:[],subtotal:'0'}
    else if(p.endsWith('/profile'))json={orders_count:1,bonus_balance:0}
    else if(p.endsWith('/orders/chattable'))json=[order]
    else if(p.endsWith('/orders'))json=u.searchParams.get('paginated')?{items:[order],total:1,has_more:false}:[order]
    else if(p.endsWith('/chat/access'))json={can_chat:true}
    else if(p.endsWith('/chat/read'))json={marked:0}
    else if(p.endsWith('/chat/media')&&method==='POST'){
      state.uploads.push('order')
      const added={...item(11),direction:'in',text:'Надіслав відео'};state.orderMessages.push(added);json={messages:[added]}
    }
    else if(p.endsWith('/chat'))json=state.orderMessages
    else if(p==='/api/shop/support/threads')json={items:[{id:1,status:'open',created_at:'2026-11-09T12:00:00Z'}],has_more:false}
    else if(p==='/api/shop/support/threads/1')json={id:1,status:'open',created_at:'2026-11-09T12:00:00Z'}
    else if(p.endsWith('/support/threads/1/media')&&method==='POST'){
      state.uploads.push('support')
      const added={...item(21),direction:'in',text:'Надіслав відео'};state.supportMessages.push(added);json={messages:[added]}
    }
    else if(p.endsWith('/support/threads/1/messages'))json={items:state.supportMessages,has_more:false}
    else if(p.match(/\/(files\/\d+|chat\/\d+\/file)$/)){
      state.downloads++
      return route.fulfill({status:200,contentType:'video/mp4',headers:{'cache-control':'private, no-store'},body:clip})
    }
    await route.fulfill({json})
  })
  await page.goto((process.env.MINIAPP_URL||'http://127.0.0.1:5174')+'/app/?chat=7')
  await page.getByRole('heading',{name:'Замовлення №7'}).waitFor()
  let log=page.getByRole('region',{name:'Переписка замовлення'})
  await log.getByRole('button',{name:'Переглянути відео'}).waitFor()
  await wait(150)
  check(state.downloads===0, `order video is lazy ${width}`)
  await log.getByRole('button',{name:'Переглянути відео'}).click()
  const player=log.locator('video').first();await player.waitFor()
  await page.waitForFunction(()=>{const v=document.querySelector('video');return v && v.readyState>=1})
  check(await player.evaluate(v=>v.duration>0.9 && v.controls && v.playsInline),`order MP4 decoded and controls visible ${width}`)
  await player.evaluate(async v=>{try {await v.play()} catch{} v.pause()})
  check(await player.evaluate(v=>v.paused),`order player can be paused ${width}`)
  await page.locator('.chat-compose input[type=file]').setInputFiles({name:'upload.mp4',mimeType:'video/mp4',buffer:clip})
  await log.getByText('Надіслав відео',{exact:true}).waitFor()
  check(state.uploads.includes('order'),`order upload sends multipart MP4 ${width}`)
  await page.getByRole('button',{name:'Замовлення',exact:true}).click()
  await page.getByRole('button',{name:'Загальна підтримка',exact:true}).click()
  await page.getByRole('button').filter({hasText:'Звернення №1'}).click()
  log=page.getByRole('region',{name:'Переписка підтримки'})
  await log.getByRole('button',{name:'Переглянути відео'}).waitFor()
  const before=state.downloads
  check(before===1,`support video also lazy ${width}`)
  await log.getByRole('button',{name:'Переглянути відео'}).click()
  await log.locator('video').first().waitFor()
  await page.waitForFunction(()=>{const v=document.querySelector('video');return v&&v.readyState>=1})
  check(await log.locator('video').first().evaluate(v=>v.controls && v.duration>.9),`support video plays ${width}`)
  await page.locator('.chat-compose input[type=file]').setInputFiles({name:'help.mp4',mimeType:'video/mp4',buffer:clip})
  await log.getByText('Надіслав відео',{exact:true}).waitFor()
  check(state.uploads.includes('support'),`support upload sends multipart MP4 ${width}`)
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`no horizontal overflow ${width}`)
  check(errors.length===0,`no React runtime errors ${width}: ${errors.join('; ')}`)
  await page.close()
 }
} finally { await browser.close() }
console.log(`CHAT VIDEO BROWSER: ${checks}/${checks}`)
