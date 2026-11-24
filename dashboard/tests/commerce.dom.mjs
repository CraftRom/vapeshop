import test from 'node:test'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {JSDOM} from 'jsdom'

const root=fileURLToPath(new URL('../',import.meta.url))
const built=await build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {MemoryRouter,useLocation} from 'react-router-dom';import Workspace from './src/components/CommerceWorkspace';import Orders from './src/pages/Orders';import Catalog from './src/pages/Catalog';import {setSession} from './src/api';setSession({role:window.testRole,csrf_token:'a'.repeat(48)});function Page(){const location=useLocation();return <><output id="test-route">{location.pathname+location.search}</output>{window.testPage==='orders'?<Orders/>:window.testPage==='catalog'?<Catalog/>:<Workspace/>}</>};createRoot(document.getElementById('root')).render(<MemoryRouter initialEntries={[window.location.pathname+window.location.search]}><Page/></MemoryRouter>);`,resolveDir:root,loader:'jsx'},bundle:true,write:false,format:'iife',jsx:'automatic',loader:{'.css':'empty'},define:{'import.meta.env.VITE_API_URL':'""','process.env.NODE_ENV':'"test"'}})
const bundle=built.outputFiles[0].text
const response=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}})
const order={id:12,contact_surname:'Покупець',contact_name:'Покупець Дмитро',contact_patronymic:'',contact_phone:'+380671234567',status:'new',payment_method:null,total:'100',items:[],created_at:'2026-11-16T08:00:00Z',user:{id:1},attribution:{source:'google',channel:'telegram_bot'}}
const state={generated_at:'2026-11-16T08:00:00Z',orders:{new:1,open:1,without_tracking:1},channels:{bot:1,miniapp:0,unknown:0},stock:{available:3,low:1,out:2,unpriced:4,missing_photos:2},low_stock_threshold:3,queue:[{...order,name:order.contact_name,phone:order.contact_phone}],products:[{id:9,name:'Реальний товар',stock:2,price:'100'}]}
async function waitFor(check){const until=Date.now()+4500;while(Date.now()<until){if(check())return;await new Promise(resolve=>setTimeout(resolve,15))}assert.ok(check(),'Dashboard DOM did not become ready')}
const button=(document,text)=>[...document.querySelectorAll('button')].find(node=>node.textContent.trim()===text)
function mount({page='workspace',path='/',role='admin',fail=false,catalogResponse=null}={}){
 const dom=new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>',{url:'https://dashboard.example.test'+path,runScripts:'outside-only',pretendToBeVisual:true})
 const window=dom.window,calls=[]
 let failure=fail
 window.Headers=Headers;window.testPage=page;window.testRole=role;window.scrollTo=()=>{};window.confirm=()=>true
 window.fetch=async(input,options={})=>{
  const url=new URL(input,window.location.href);calls.push({url,options})
  if(url.pathname==='/api/orders/operations')return failure?response({detail:'Тимчасова помилка'},503):response(state)
  if(url.pathname==='/api/orders')return response({items:[order],total:1})
  if(url.pathname==='/api/orders/salesdrive-statuses')return response({statuses:[]})
  if(url.pathname==='/api/orders/unread/counts')return response({})
  if(url.pathname==='/api/catalog/categories'||url.pathname==='/api/catalog/subcategories')return response([])
  if(url.pathname==='/api/catalog/products'){
   if(catalogResponse)return catalogResponse(url)
   if(failure)return response({detail:'Каталог тимчасово недоступний'},503)
   const offset=Number(url.searchParams.get('offset')||0)
   return response({items:[{id:offset+1,sku:'REAL-'+offset,name:'Товар сторінки '+(offset/20+1),brand:'Бренд',price:'100',stock:2,is_active:true,has_photo:false}],total:521,limit:20,offset})
  }
  return response({},404)
 }
 window.eval(bundle)
 return {window,document:window.document,calls,recover:()=>{failure=false},close:()=>window.close()}
}

test('operational workspace renders database values and links to exact working queues',async()=>{
 const app=mount()
 try{
  await waitFor(()=>app.document.querySelectorAll('.commerce-tile').length===4)
  assert.equal(app.document.querySelector('.commerce-tile').getAttribute('href'),'/orders?queue=new')
  assert.match(app.document.querySelector('.commerce-queue').textContent,/Покупець Дмитро/)
  assert.equal(app.document.querySelector('.commerce-stock a[href^="/catalog/products"]').getAttribute('href'),'/catalog/products/9')
 }finally{app.close()}
})
test('manager does not see moderation controls even if a response includes them',async()=>{
 const app=mount({role:'operator'})
 try{await waitFor(()=>app.document.querySelector('.commerce-readiness'));assert.doesNotMatch(app.document.querySelector('.commerce-readiness').textContent,/модерації/)}finally{app.close()}
})
test('workspace has an explicit recoverable error instead of fabricated counts',async()=>{
 const app=mount({fail:true})
 try{
  await waitFor(()=>button(app.document,'Спробувати ще раз'))
  assert.equal(app.document.querySelectorAll('.commerce-tile').length,0)
  app.recover();button(app.document,'Спробувати ще раз').click()
  await waitFor(()=>app.document.querySelectorAll('.commerce-tile').length===4)
 }finally{app.close()}
})
test('order filters are stored in URL and sent to the server together',async()=>{
 const app=mount({page:'orders',path:'/orders?channel=bot&queue=new&payment=cod&delivery=warehouse'})
 try{
  await waitFor(()=>app.document.querySelector('.order-row'))
  const call=app.calls.find(call=>call.url.pathname==='/api/orders')
  for(const [key,value] of Object.entries({channel:'bot',queue:'new',payment_method:'cod',delivery_method:'warehouse'}))assert.equal(call.url.searchParams.get(key),value)
  const select=app.document.querySelector('.commerce-order-filters select');select.value='miniapp';select.dispatchEvent(new app.window.Event('change',{bubbles:true}))
  await waitFor(()=>app.calls.some(call=>call.url.pathname==='/api/orders'&&call.url.searchParams.get('channel')==='miniapp'))
  assert.match(app.document.querySelector('#test-route').textContent,/channel=miniapp/)
 }finally{app.close()}
})
test('order details do not duplicate recipient names or invent a payment method',async()=>{
 const app=mount({page:'orders',path:'/orders'})
 try{
  await waitFor(()=>button(app.document,'Швидкий перегляд'))
  button(app.document,'Швидкий перегляд').click()
  await waitFor(()=>app.document.querySelector('[role="dialog"]'))
  const text=app.document.querySelector('[role="dialog"]').textContent
  assert.doesNotMatch(text,/Покупець Покупець/)
  assert.match(app.document.querySelector('.order-payment-method').textContent,/не вказано/)
 }finally{app.close()}
})
test('catalog loads deep pages on the server and preserves filters on next page',async()=>{
 const app=mount({page:'catalog',path:'/catalog?page=26&inventory=low&sort=stock-asc'})
 try{
  await waitFor(()=>app.document.querySelector('.catalog-product-link'))
  const call=app.calls.find(call=>call.url.pathname==='/api/catalog/products')
  assert.equal(call.url.searchParams.get('offset'),'500');assert.equal(call.url.searchParams.get('limit'),'20');assert.equal(call.url.searchParams.get('paginated'),'true')
  assert.equal(call.url.searchParams.get('inventory'),'low');assert.equal(call.url.searchParams.get('sort'),'stock-asc')
  assert.match(app.document.querySelector('.catalog-found').textContent,/521/)
  app.document.querySelector('[aria-label="Наступна сторінка"]').click()
  await waitFor(()=>app.calls.some(call=>call.url.pathname==='/api/catalog/products'&&call.url.searchParams.get('offset')==='520'))
  assert.match(app.document.querySelector('#test-route').textContent,/inventory=low/)
 }finally{app.close()}
})
test('catalog error ends the loading state and offers retry',async()=>{
 const app=mount({page:'catalog',path:'/catalog',fail:true})
 try{
  await waitFor(()=>button(app.document,'Повторити'))
  assert.equal(app.document.querySelector('.catalog-product-link'),null)
  assert.equal(app.document.querySelector('[aria-busy=true]'),null)
  app.recover();button(app.document,'Повторити').click()
  await waitFor(()=>app.document.querySelector('.catalog-product-link'))
 }finally{app.close()}
})


test('new catalog filter never labels an old page as its own results',async()=>{
 let resolveNext
 const pending=new Promise(resolve=>{resolveNext=resolve})
 const app=mount({page:'catalog',path:'/catalog',catalogResponse:url=>url.searchParams.get('inventory')==='low'?pending:response({items:[{id:1,name:'Старий відбір',sku:'OLD',price:100,stock:2,is_active:true}],total:1})})
 try{
  await waitFor(()=>app.document.querySelector('.catalog-product-link'))
  const select=app.document.querySelector('[aria-label="Стан товарів"]');select.value='low';select.dispatchEvent(new app.window.Event('change',{bubbles:true}))
  await waitFor(()=>app.calls.some(call=>call.url.pathname==='/api/catalog/products'&&call.url.searchParams.get('inventory')==='low'))
  assert.equal(app.document.querySelector('.catalog-product-link'),null)
  resolveNext(response({items:[{id:2,name:'Новий відбір',sku:'NEW',price:100,stock:1,is_active:true}],total:1}))
  await waitFor(()=>app.document.querySelector('.catalog-product-link')?.textContent==='Новий відбір')
 }finally{app.close()}
})
