import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const browser = await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH || undefined,args:['--no-sandbox']})
let checks=0
const check=(value,label)=>{assert.ok(value,label);checks++;console.log('PASS '+label)}
try {
  for (const width of [1280,390]) {
    const page=await browser.newPage({viewport:{width,height:820}})
    const errors=[];page.on('pageerror',e=>errors.push(e.message))
    const calls=[]
    const time='2026-10-13T13:00:00Z'
    const items=[
      {id:1,title:'Тест завершення',text:'QA',status:'sent',sent_count:50,failed_count:2,unknown_count:1,heartbeat_at:time,last_error:'Втрачено відповідь',created_at:time},
      {id:2,title:'Тест відновлення',text:'QA',status:'sending',sent_count:2,failed_count:0,unknown_count:0,heartbeat_at:time,lease_until:time,created_at:time},
      {id:3,title:'Тест продовження',text:'QA',status:'failed',sent_count:2,failed_count:0,unknown_count:0,created_at:time},
    ]
    await page.route('**/api/**',async route=>{
      const url=new URL(route.request().url()), p=url.pathname
      let data={}
      if(p==='/api/auth/session')data={role:'admin',name:'QA',csrf_token:'test'}
      else if(p.includes('notifications'))data={items:[],unread:0}
      else if(p.includes('badges'))data={orders_new:0,support_unread:0}
      else if(p==='/api/broadcasts/segments')data=[{type:'all',label:'Усі клієнти'}]
      else if(p==='/api/broadcasts')data=items
      else if(p==='/api/broadcasts/1/deliveries'){
        const after=Number(url.searchParams.get('after')||0);calls.push(after)
        data=after ? {items:[{user_id:51,status:'unknown',attempts:1,error:'Втрачено відповідь',updated_at:time}],next_cursor:null}
          : {items:Array.from({length:50},(_,i)=>({user_id:i+1,status:i===0?'retry':'sent',attempts:1,next_attempt_at:i===0?time:null,updated_at:time})),next_cursor:50}
      }
      await route.fulfill({json:data})
    })
    await page.goto((process.env.DASHBOARD_URL||'http://127.0.0.1:5173')+'/broadcasts')
    const done=page.getByRole('row').filter({hasText:'Тест завершення'})
    await done.waitFor()
    check((await done.innerText()).includes('1 невідомих результатів'),'unknown count '+width)
    check((await done.innerText()).includes('Завершено'),'completion label '+width)
    check((await page.getByRole('row').filter({hasText:'Тест відновлення'}).innerText()).includes('Очікує автоматичного відновлення'),'recovery state '+width)
    check(await page.getByRole('row').filter({hasText:'Тест продовження'}).getByRole('button',{name:'Продовжити',exact:true}).isVisible(),'failed resume '+width)
    await done.getByRole('button',{name:'Журнал',exact:true}).click()
    const modal=page.getByRole('dialog')
    await modal.getByRole('button',{name:'Далі',exact:true}).waitFor()
    await modal.getByText('#1',{exact:true}).waitFor()
    await modal.getByText('Очікує повтору',{exact:true}).waitFor()
    check(await modal.getByText('Очікує повтору',{exact:true}).isVisible(),'retry entry '+width)
    await modal.getByRole('button',{name:'Далі',exact:true}).click()
    await modal.getByText('#51',{exact:true}).waitFor()
    check(await modal.getByText('Результат невідомий',{exact:true}).isVisible(),'unknown journal result '+width)
    check(!await modal.getByText('#1',{exact:true}).count(),'pagination replaces page '+width)
    await modal.getByRole('button',{name:'На початок',exact:true}).click()
    await modal.getByText('#1',{exact:true}).waitFor()
    check(calls.filter((value,index)=>index===0||value!==calls[index-1]).join(',')==='0,50,0','journal cursor '+width)
    const box=await modal.boundingBox()
    check(box.x>=0 && box.x+box.width<=width,'modal fits viewport '+width)
    if (process.env.QA_CAPTURE_DIR) await page.screenshot({path:`${process.env.QA_CAPTURE_DIR}/broadcast-journal-${width}.png`})
    check(await modal.evaluate(el=>el.contains(document.activeElement)),'focus stays in dialog '+width)
    await page.keyboard.press('Escape')
    await modal.waitFor({state:'hidden'})
    check(errors.length===0,'no runtime errors '+width)
    await page.close()
  }
  console.log(`BROADCAST BROWSER: ${checks}/${checks}`)
} finally {await browser.close()}
