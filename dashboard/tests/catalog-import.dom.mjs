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
