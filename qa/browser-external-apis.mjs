import { chromium } from 'playwright'
import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
const html=readFileSync(new URL('./output/external-google-fixture.html',import.meta.url),'utf8')
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH,args:['--no-sandbox']})
let checks=0
const check=(ok,label)=>{assert.ok(ok,label);checks++;console.log('PASS '+label)}
try {
 const page=await browser.newPage();let navigations=0,googleLoads=0
 await page.route('https://www.googletagmanager.com/**',async route=>{googleLoads++;await route.fulfill({body:'/* Google network intentionally stubbed in QA */',contentType:'application/javascript'})})
 await page.route('https://promo.example/**',async route=>{
  const path=new URL(route.request().url()).pathname
  if(path==='/go'){navigations++;return route.fulfill({body:'Arrived',contentType:'text/html'})}
  await route.fulfill({body:html,contentType:'text/html'})
 })
 const load=async()=>{await page.goto('https://promo.example/');await page.locator('.cta').waitFor()}
 await load()
 check(googleLoads===1,'one Google loader per page')
 check(await page.evaluate(()=>dataLayer.findIndex(x=>x[0]==='consent')<dataLayer.findIndex(x=>x[0]==='config')),'consent defaults are queued before config in the browser')
 await page.locator('[data-consent="deny"]').click()
 check(await page.evaluate(()=>localStorage.getItem('promo_google_consent')==='denied'),'consent choice persists without sending real Google events')
 const modifier=await page.locator('.cta').evaluate(link=>{
  const allowed=link.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,button:0,ctrlKey:true}))
  const event=[...dataLayer].reverse().find(x=>x[0]==='event'&&x[1]==='conversion')
  event[2].event_callback();return {allowed,timeout:event[2].event_timeout}
 })
 check(modifier.allowed&&modifier.timeout===1000&&page.url()==='https://promo.example/','Ctrl-click is not hijacked and its callback does not redirect current tab')
 await page.locator('.cta').click()
 await page.evaluate(()=>{const event=[...dataLayer].reverse().find(x=>x[0]==='event'&&x[1]==='conversion');event[2].event_callback();event[2].event_callback()})
 await page.waitForURL('https://promo.example/go')
 check(navigations===1,'conversion callback navigates exactly once')
 await load();await page.locator('.cta').click();await page.waitForURL('https://promo.example/go')
 check(navigations===2,'fallback navigation works when Google callback never arrives')
 console.log(`EXTERNAL API BROWSER: ${checks}/${checks}`)
} finally {await browser.close()}
