import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const browser = await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH,args:['--no-sandbox','--disable-dev-shm-usage']})
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aHTsAAAAASUVORK5CYII=', 'base64')
let checks=0
const check=(condition,label)=>{assert.ok(condition,label);checks++;console.log('PASS '+label)}
try {
 for(const width of [320,390,1280]) {
  const page=await browser.newPage({viewport:{width,height:900},timezoneId:'Europe/Kyiv'})
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  const items=[];let creates=0,sends=0,uploads=0,schedules=0,libraryFail=true,uploadHold=null,sendHold=null
  let lastPayload,lastSchedule,holdUpload=false,holdSend=false
  await page.route('**/media/**',route=>route.fulfill({contentType:'image/png',body:png}))
  await page.route('**/api/**',async route=>{
   const request=route.request(),url=new URL(request.url()),path=url.pathname,method=request.method()
   let data={}
   if(path==='/api/auth/session')data={role:'admin',name:'QA',csrf_token:'qa'}
   else if(path==='/api/broadcasts/segments')data=[{type:'all',label:'Усі клієнти'},{type:'inactive',label:'Не заходили N днів'}]
   else if(path==='/api/broadcasts/preview')data={count:264}
   else if(path==='/api/media' && method==='POST') {
    uploads++;check(request.headers()['x-csrf-token']==='qa',`${width}: upload preserves CSRF`)
    if(holdUpload){holdUpload=false;await new Promise(resolve=>{uploadHold=resolve})}
    data={url:`/media/upload-${uploads}.png`,name:`upload-${uploads}.png`}
   } else if(path==='/api/media') {
    if(libraryFail)return route.fulfill({status:503,json:{detail:'Сховище тимчасово недоступне'}})
    const search=url.searchParams.get('search')||'',offset=Number(url.searchParams.get('offset')||0)
    const all=Array.from({length:30},(_,i)=>({name:`image-${i}.png`,url:`/media/image-${i}.png`,sizeBytes:1024}))
    const filtered=all.filter(f=>f.name.includes(search))
    data={files:filtered.slice(offset,offset+24),total:filtered.length,storedTotal:30,totalBytes:30720,has_more:offset+24<filtered.length}
   } else if(path==='/api/broadcasts' && method==='POST') {
    creates++;lastPayload=request.postDataJSON();check(request.headers()['x-csrf-token']==='qa',`${width}: create preserves CSRF`)
    data={...lastPayload,id:creates,status:'draft',sent_count:0,failed_count:0,unknown_count:0,created_at:'2026-11-02T12:00:00Z'};items.unshift(data)
   } else if(path==='/api/broadcasts')data=items
   else if(/^\/api\/broadcasts\/\d+$/.test(path)) {
    const index=items.findIndex(b=>b.id===Number(path.split('/').at(-1)))
    if(method==='PUT'){lastPayload=request.postDataJSON();items[index]={...items[index],...lastPayload}}
    data=items[index]
   } else if(path.endsWith('/send')) {
    sends++;const index=items.findIndex(b=>b.id===Number(path.split('/').at(-2)))
    if(sends===1) {
     if(width===390)items[index].status='sending'
     return route.fulfill({status:503,json:{detail:'Не вдалося отримати результат запуску'}})
    }
    if(holdSend){holdSend=false;await new Promise(resolve=>{sendHold=resolve})}
    items[index].status='sending';data=items[index]
   } else if(path.endsWith('/schedule')) {
    schedules++;lastSchedule=request.postDataJSON();const index=items.findIndex(b=>b.id===Number(path.split('/').at(-2)))
    items[index]={...items[index],status:'scheduled',scheduled_at:lastSchedule.scheduled_at};data=items[index]
   } else if(path.includes('notifications'))data={items:[],unread:0}
   else if(path.includes('badges'))data={orders_new:0,support_unread:0}
   else if(path.includes('statuses'))data={statuses:[]}
   await route.fulfill({json:data})
  })
  await page.goto('http://127.0.0.1:5173/broadcasts')
  await page.getByRole('button',{name:'Створити розсилку',exact:true}).click()
  const form=page.getByRole('dialog',{name:'Нова розсилка',exact:true})
  const send=form.getByRole('button',{name:'Надіслати зараз',exact:true})
  const draft=form.getByRole('button',{name:'Зберегти чернетку',exact:true})
  check(await send.isDisabled(),`${width}: empty form cannot send`)
  await form.getByLabel('Назва розсилки',{exact:true}).fill('Фото пропозиція')
  await form.getByLabel('Текст повідомлення',{exact:true}).fill('Ціна < 100 & доставка > 0')
  await page.waitForFunction(()=>document.querySelector('.broadcast-reach')?.textContent.includes('264'))
  check(await send.isEnabled() && await form.getByRole('radio',{name:'Текст',exact:true}).isChecked(),`${width}: plain text mode accepts literal special characters`)
  await form.getByRole('button',{name:'Обрати зі сховища',exact:true}).click()
  const library=page.getByRole('dialog',{name:'Сховище зображень',exact:true})
  await library.getByText('Сховище тимчасово недоступне',{exact:true}).waitFor()
  libraryFail=false;await library.getByRole('button',{name:'Повторити завантаження'}).click()
  await library.getByRole('button',{name:'Вибрати image-0.png',exact:true}).waitFor()
  await page.keyboard.press('Escape');await library.waitFor({state:'hidden'})
  check(await form.isVisible() && await form.getByLabel('Назва розсилки').inputValue()==='Фото пропозиція',`${width}: Escape closes only image library and preserves form`)
  check(await form.evaluate(el=>el.contains(document.activeElement)),`${width}: focus returns to broadcast editor`)
  await form.getByRole('button',{name:'Обрати зі сховища',exact:true}).click()
  await library.getByRole('button',{name:'Вибрати image-0.png',exact:true}).waitFor()
  await library.getByRole('button',{name:'Наступна',exact:true}).click()
  await library.getByRole('button',{name:'Вибрати image-24.png',exact:true}).waitFor()
  await library.getByLabel('Пошук зображень').fill('image-29')
  await library.getByRole('button',{name:'Вибрати image-29.png',exact:true}).click()
  await library.waitFor({state:'hidden'})
  check(await form.getByRole('button',{name:'Прибрати зображення',exact:true}).isVisible(),`${width}: old library image selected through server search`)
  await form.getByLabel('Текст повідомлення',{exact:true}).fill('x'.repeat(1025))
  check(await send.isDisabled() && await form.getByText(/Ліміт 1024 знаків/).isVisible(),`${width}: photo caption limit prevents invalid delivery`)
  await form.getByRole('button',{name:'Прибрати зображення',exact:true}).click()
  check(await send.isEnabled(),`${width}: removing photo restores 4096-character text limit`)
  await form.getByLabel('Текст повідомлення',{exact:true}).fill('Ціна < 100 & доставка > 0')
  const fileInput=form.getByLabel('Завантажити: Зображення розсилки',{exact:true})
  await fileInput.setInputFiles({name:'wrong.txt',mimeType:'text/plain',buffer:Buffer.from('text')})
  await form.getByText(/Інші формати не підтримуються/).waitFor()
  check(uploads===0,`${width}: invalid file rejected before request`)
  await fileInput.setInputFiles({name:'large.png',mimeType:'image/png',buffer:Buffer.alloc(8*1024*1024+1)})
  await form.getByText(/Файл більший за 8 МБ/).waitFor()
  check(uploads===0,`${width}: oversize file rejected before request`)
  holdUpload=true
  await fileInput.setInputFiles({name:'photo.png',mimeType:'image/png',buffer:png})
  await form.getByRole('button',{name:'Завантажуємо…',exact:true}).waitFor()
  check(await send.isDisabled() && await draft.isDisabled(),`${width}: draft and send wait for image upload`)
  await page.keyboard.press('Escape');check(await form.isVisible(),`${width}: uploading form is kept open`)
  await page.waitForFunction(()=>document.querySelector('.broadcast-preview')?.textContent.includes('Завантаження фото'))
  while(!uploadHold)await page.waitForTimeout(20);uploadHold();uploadHold=null
  await form.getByRole('button',{name:'Прибрати зображення',exact:true}).waitFor()
  check(await send.isEnabled(),`${width}: successful upload enables sending`)
  await form.getByLabel('Текст кнопки',{exact:true}).fill('Магазин')
  check(await send.isDisabled(),`${width}: incomplete button cannot send`)
  await form.getByLabel('Посилання кнопки',{exact:true}).fill('https://t.me/elfarshop_bot/elfar')
  check(await send.isEnabled(),`${width}: complete button allowed`)
  await form.screenshot({path:`qa/output/broadcast-compose-${width}.png`})
  check(await form.evaluate(el=>el.scrollWidth<=el.clientWidth) && await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width}: form fits viewport without horizontal overflow`)
  await send.click()
  await form.getByText('Не вдалося отримати результат запуску',{exact:true}).waitFor()
  check(creates===1 && sends===1 && lastPayload.photo_url==='/media/upload-1.png' && lastPayload.text_format==='plain',`${width}: photo and plain text saved once before launch failure`)
  check(await form.getByLabel('Текст повідомлення').inputValue()==='Ціна < 100 & доставка > 0',`${width}: launch failure retains composed message`)
  if(width!==390)holdSend=true
  await send.evaluate(button=>{button.click();button.click()})
  if(width!==390) {
    await form.getByRole('button',{name:'Запускаємо…',exact:true}).waitFor()
    await page.keyboard.press('Escape');check(await form.isVisible(),`${width}: pending send cannot close form`)
    while(!sendHold)await page.waitForTimeout(20)
    check(creates===1 && sends===2,`${width}: retry and double click reuse the same draft`)
    sendHold();sendHold=null
  }
  await form.waitFor({state:'hidden'})
  check(creates===1 && sends===(width===390?1:2),`${width}: lost launch response does not create or enqueue duplicate`)
  await page.getByRole('button',{name:'Створити розсилку',exact:true}).click()
  await form.getByLabel('Назва розсилки',{exact:true}).fill('Текстова чернетка')
  await form.getByLabel('Текст повідомлення',{exact:true}).fill('Просто текст < і > та &')
  if(width===1280) {
   const drop=form.locator('.image-field')
   await drop.evaluate((el,base64)=>{const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));const data=new DataTransfer();data.items.add(new File([bytes],'dropped.png',{type:'image/png'}));el.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:data}))},png.toString('base64'))
   await form.getByRole('button',{name:'Прибрати зображення',exact:true}).waitFor()
   check(uploads===2,`${width}: dropping an image uploads it`)
   await form.getByRole('button',{name:'Прибрати зображення',exact:true}).click()
   await drop.evaluate((el,base64)=>{const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));const data=new DataTransfer();data.items.add(new File([bytes],'pasted.png',{type:'image/png'}));el.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}))},png.toString('base64'))
   await form.getByRole('button',{name:'Прибрати зображення',exact:true}).waitFor()
   check(uploads===3,`${width}: pasting an image uploads it`)
   await form.getByRole('button',{name:'Прибрати зображення',exact:true}).click()
   await page.route('https://images.example.org/photo.png',route=>route.fulfill({body:png,contentType:'image/png'}))
   await form.getByRole('button',{name:'За посиланням',exact:true}).click()
   await form.getByLabel('Пряме посилання на зображення',{exact:true}).fill('https://images.example.org/photo.png')
   check(await form.getByRole('button',{name:'Прибрати зображення',exact:true}).isVisible(),`${width}: direct image link adds a preview`)
   await form.getByRole('button',{name:'Прибрати зображення',exact:true}).click()
  }
  await draft.click();await form.waitFor({state:'hidden'})
  check(creates===2 && lastPayload.photo_url===null && lastPayload.text_format==='plain',`${width}: text-only draft stores no photo`)
  const card=page.getByRole('article',{name:'Текстова чернетка',exact:true})
  await card.getByRole('button',{name:'Редагувати',exact:true}).click()
  const editor=page.getByRole('dialog',{name:'Редагувати розсилку',exact:true})
  await editor.getByRole('radio',{name:'HTML',exact:true}).check()
  await editor.getByLabel('Текст повідомлення',{exact:true}).fill('<b>Жирний</b> та <i>курсив</i>')
  check(await editor.locator('.broadcast-message-text b').innerText()==='Жирний',`${width}: safe HTML preview shows formatting`)
  await editor.getByRole('button',{name:'Зберегти чернетку',exact:true}).click();await editor.waitFor({state:'hidden'})
  check(creates===2 && lastPayload.text_format==='html',`${width}: editing updates existing draft without new creation`)
  await card.getByRole('button',{name:'Редагувати',exact:true}).click()
  const launchTime=editor.getByLabel('Час запуску',{exact:true})
  check(await launchTime.getAttribute('step')==='60',`${width}: schedule accepts minutes`)
  await launchTime.fill('2020-02-03T12:37')
  await editor.getByRole('button',{name:'Запланувати',exact:true}).click()
  await editor.getByText('Виберіть час запуску в майбутньому',{exact:true}).waitFor()
  check(schedules===0,`${width}: past schedule is rejected without a schedule request`)
  await launchTime.fill('2027-02-03T12:37')
  await editor.getByRole('button',{name:'Запланувати',exact:true}).click();await editor.waitFor({state:'hidden'})
  check(schedules===1 && lastSchedule.scheduled_at==='2027-02-03T10:37:00.000Z',`${width}: scheduling preserves selected minutes and submits explicit UTC from device time`)
  await page.getByLabel('Пошук розсилок',{exact:true}).fill('Текстова')
  check(await page.locator('.broadcast-card').count()===1,`${width}: list search finds the requested campaign`)
  await page.getByLabel('Статус розсилок',{exact:true}).selectOption('draft')
  await page.getByText('Нічого не знайдено',{exact:true}).waitFor()
  await page.getByRole('button',{name:'Скинути фільтри',exact:true}).click()
  check(await page.locator('.broadcast-card').count()===2,`${width}: clearing filters restores full list`)
  await page.screenshot({path:`qa/output/broadcast-list-${width}.png`,fullPage:true})
  check(errors.length===0,`${width}: no React errors ${errors.join('; ')}`)
  await page.close()
 }
 console.log(`BROADCAST COMPOSE BROWSER: ${checks}/${checks}`)
} finally {await browser.close()}
