import test from 'node:test'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {JSDOM} from 'jsdom'
const root=fileURLToPath(new URL('../',import.meta.url))
const bundle=(await build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {MemoryRouter} from 'react-router-dom';import Catalog from './src/pages/Catalog';import {setSession} from './src/api';setSession({role:'admin',csrf_token:'x'});createRoot(document.getElementById('root')).render(<MemoryRouter><Catalog/></MemoryRouter>);`,resolveDir:root,loader:'jsx'},bundle:true,write:false,format:'iife',jsx:'automatic',loader:{'.css':'empty'},define:{'import.meta.env.VITE_API_URL':'""','process.env.NODE_ENV':'"test"'}})).outputFiles[0].text
async function waitFor(check){const until=Date.now()+3000;while(Date.now()<until){if(check())return;await new Promise(r=>setTimeout(r,15))}assert.ok(check())}
function button(dom,text){return [...dom.window.document.querySelectorAll('button')].find(n=>n.textContent.trim()===text)}
test('catalog import opens without parent filter variables and rejects oversize XLSX before POST',async()=>{
 const dom=new JSDOM('<div id="root"></div>',{url:'https://dashboard.accordniche.pp.ua/catalog',runScripts:'outside-only',pretendToBeVisual:true})
 let posts=0;const errors=[]
 dom.window.addEventListener('error',e=>errors.push(e.error))
 dom.window.Headers=Headers
 dom.window.fetch=async(url,options={})=>{
  if(options.method==='POST')posts++
  return new Response(JSON.stringify(new URL(url).pathname.endsWith('/products')?{items:[],total:0}:[]),{headers:{'content-type':'application/json'}})
 }
 try{
  dom.window.eval(bundle)
  await waitFor(()=>button(dom,'Імпорт XLSX'))
  button(dom,'Імпорт XLSX').click()
  await waitFor(()=>dom.window.document.querySelector('[role="dialog"]'))
  assert.match(dom.window.document.querySelector('[role="dialog"]').textContent,/до 10 МіБ/)
  assert.equal(errors.length,0)
  const file=new dom.window.File(['x'],'products.xlsx');Object.defineProperty(file,'size',{value:10*1024*1024+1})
  const input=dom.window.document.querySelector('[role="dialog"] input[type=file]')
  Object.defineProperty(input,'files',{value:[file]});input.dispatchEvent(new dom.window.Event('change',{bubbles:true}))
  await waitFor(()=>!button(dom,'Імпортувати').disabled)
  button(dom,'Імпортувати').click()
  await waitFor(()=>dom.window.document.body.textContent.includes('Файл завеликий'))
  assert.equal(posts,0);assert.equal(errors.length,0)
 }finally{dom.window.close()}
})
test('accepted import shows durable progress and the final summary from the job',async()=>{
 const dom=new JSDOM('<div id="root"></div>',{url:'https://dashboard.accordniche.pp.ua/catalog',runScripts:'outside-only',pretendToBeVisual:true})
 const errors=[];let polls=0
 dom.window.addEventListener('error',e=>errors.push(e.error))
 dom.window.Headers=Headers
 const job={job_id:'a'.repeat(64),status:'queued',rows_total:3,rows_done:0,attempts:0,error:null,result:null,replayed:false}
 dom.window.fetch=async(url,options={})=>{
  const path=new URL(url).pathname
  if(options.method==='POST'&&path.endsWith('/product-transfer/import'))return new Response(JSON.stringify(job),{status:202,headers:{'content-type':'application/json'}})
  if(path.endsWith('/product-transfer/import/'+job.job_id)){polls++;const body=polls<2?{...job,status:'running',rows_done:2}:{...job,status:'done',rows_done:3,result:{rows:3,created:1,updated:2,skipped:0,sku_generated:1,prices_changed:0,errors:[]}};return new Response(JSON.stringify(body),{headers:{'content-type':'application/json'}})}
  return new Response(JSON.stringify(path.endsWith('/products')?{items:[],total:0}:[]),{headers:{'content-type':'application/json'}})
 }
 try{
  dom.window.eval(bundle)
  await waitFor(()=>button(dom,'Імпорт XLSX'))
  button(dom,'Імпорт XLSX').click()
  await waitFor(()=>dom.window.document.querySelector('[role="dialog"]'))
  const file=new dom.window.File(['x'],'products.xlsx')
  const input=dom.window.document.querySelector('[role="dialog"] input[type=file]')
  Object.defineProperty(input,'files',{value:[file]});input.dispatchEvent(new dom.window.Event('change',{bubbles:true}))
  await waitFor(()=>!button(dom,'Імпортувати').disabled)
  button(dom,'Імпортувати').click()
  await waitFor(()=>dom.window.document.body.textContent.includes('Імпорт у черзі'))
  assert.equal(dom.window.sessionStorage.getItem('accord:catalog-import-job'),job.job_id,'job survives a reload')
  await waitFor(()=>dom.window.document.body.textContent.includes('Оброблено 2 із 3'))
  const until=Date.now()+5000
  while(Date.now()<until&&!dom.window.document.body.textContent.includes('додано: 1'))await new Promise(r=>setTimeout(r,50))
  assert.match(dom.window.document.body.textContent,/Рядків: 3 · додано: 1 · оновлено: 2/)
  assert.equal(dom.window.sessionStorage.getItem('accord:catalog-import-job'),null)
  assert.equal(errors.length,0)
 }finally{dom.window.close()}
})
