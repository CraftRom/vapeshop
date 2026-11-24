import test from 'node:test'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {JSDOM} from 'jsdom'
const root=fileURLToPath(new URL('../',import.meta.url))
const bundle=(await build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import Backups from './src/pages/Backups';import {setSession} from './src/api';setSession({role:'admin',csrf_token:'x'});createRoot(document.getElementById('root')).render(<Backups/>);`,resolveDir:root,loader:'jsx'},bundle:true,write:false,format:'iife',jsx:'automatic',loader:{'.css':'empty'},define:{'import.meta.env.VITE_API_URL':'""','process.env.NODE_ENV':'"test"'}})).outputFiles[0].text
async function waitFor(check){const until=Date.now()+3000;while(Date.now()<until){if(check())return;await new Promise(r=>setTimeout(r,15))}assert.ok(check())}
test('backup instructions do not run a live database restoration',async()=>{
 const dom=new JSDOM('<div id="root"></div>',{url:'https://dashboard.example.test/backups',runScripts:'outside-only',pretendToBeVisual:true})
 const calls=[];dom.window.Headers=Headers
 dom.window.fetch=async(url,options={})=>{calls.push({url,method:options.method||'GET'});return new Response(JSON.stringify({restoreMode:'server',items:[{name:'elfar-manual-test.dump',sizeBytes:1024,createdAt:'2026-11-16T10:00:00Z'}],total:1,totalBytes:1024,freeBytes:1024,retentionDays:14}),{headers:{'content-type':'application/json'}})}
 try{
  dom.window.eval(bundle)
  await waitFor(()=>[...dom.window.document.querySelectorAll('button')].some(n=>n.textContent.trim()==='Як відновити'))
  ;[...dom.window.document.querySelectorAll('button')].find(n=>n.textContent.trim()==='Як відновити').click()
  await waitFor(()=>dom.window.document.querySelector('[role="dialog"]'))
  assert.match(dom.window.document.querySelector('[role="dialog"]').textContent,/Відновлення на сервері/)
  assert.match(dom.window.document.querySelector('[role="dialog"]').textContent,/Кнопка у браузері не змінює базу/)
  assert.equal(calls.some(c=>c.method!=='GET'),false)
 }finally{dom.window.close()}
})

const listFixture={items:[],total:0,totalBytes:0,freeBytes:1024,retentionDays:14}
function response(value,status=200){return new Response(JSON.stringify(value),{status,headers:{'content-type':'application/json'}})}
function backupDom(fetch,saved){
 const dom=new JSDOM('<div id="root"></div>',{url:'https://dashboard.example.test/backups',runScripts:'outside-only',pretendToBeVisual:true})
 dom.window.Headers=Headers;dom.window.fetch=fetch
 if(saved)dom.window.sessionStorage.setItem('elfar:backup:request',JSON.stringify(saved))
 dom.window.eval(bundle)
 return dom
}
function button(dom,text){return [...dom.window.document.querySelectorAll('button')].find(n=>n.textContent.includes(text))}

test('lost response and page reload reuse the persisted request key',async()=>{
 const keys=[]
 let dom=backupDom(async(url,options={})=>{
  const path=new URL(url).pathname
  if(path.endsWith('/jobs')&&options.method==='POST'){keys.push(JSON.parse(options.body).client_key);throw new TypeError('Connection lost')}
  return response(path.endsWith('/jobs')?{jobs:[],worker:{available:false}}:listFixture)
 })
 let saved
 try{
  await waitFor(()=>button(dom,'Зробити копію зараз')&&!button(dom,'Зробити копію зараз').disabled)
  button(dom,'Зробити копію зараз').click()
  await waitFor(()=>dom.window.document.body.textContent.includes('ключ збережено'))
  saved=JSON.parse(dom.window.sessionStorage.getItem('elfar:backup:request'))
  assert.equal(saved.key,keys[0]);assert.match(saved.key,/^[a-f0-9]{32}$/)
 }finally{dom.window.close()}
 dom=backupDom(async(url,options={})=>{
  if(new URL(url).pathname.endsWith('/jobs')){
   if(options.method==='POST'){
    keys.push(JSON.parse(options.body).client_key)
    return response({id:'f'.repeat(32),status:'queued',created_at:Date.now()/1000,message:'Очікує виконавця'},202)
   }
   return response({jobs:[],worker:{available:false}})
  }
  return response(listFixture)
 },saved)
 try{
  await waitFor(()=>button(dom,'Перевірити запит')&&!button(dom,'Перевірити запит').disabled)
  button(dom,'Перевірити запит').click()
  await waitFor(()=>dom.window.document.body.textContent.includes('У черзі'))
  assert.equal(keys.length,2);assert.equal(keys[0],keys[1])
  assert.ok(button(dom,'Копія створюється').disabled)
  assert.match(dom.window.document.body.textContent,/Виконавець не відповідає/)
 }finally{dom.window.close()}
})

test('existing running job is recovered and completion refreshes files',async()=>{
 let finished=false,lists=0
 const id='c'.repeat(32)
 const dom=backupDom(async(url)=>{
  if(new URL(url).pathname.endsWith('/jobs'))return response({jobs:[{id,status:finished?'succeeded':'running',created_at:Date.now()/1000,message:finished?'Копія готова':'Створюємо копію',result:finished?{name:'elfar-job-test.dump'}:null}],worker:{available:true}})
  lists++;return response(listFixture)
 },{key:'d'.repeat(32),id})
 try{
  await waitFor(()=>dom.window.document.body.textContent.includes('Виконується'))
  assert.ok(button(dom,'Копія створюється').disabled)
  finished=true
  dom.window.document.dispatchEvent(new dom.window.Event('visibilitychange'))
  await waitFor(()=>dom.window.document.body.textContent.includes('Копія готова'))
  assert.equal(dom.window.sessionStorage.getItem('elfar:backup:request'),null)
  assert.ok(lists>=2)
  assert.ok(!button(dom,'Зробити копію зараз').disabled)
 }finally{dom.window.close()}
})

test('oversize browser backup is refused before a network write',async()=>{
 let writes=0
 const dom=backupDom(async(url,options={})=>{
  if(options.method==='POST')writes++
  return response(new URL(url).pathname.endsWith('/jobs')?{jobs:[],worker:{available:true}}:listFixture)
 })
 try{
  await waitFor(()=>button(dom,'Зробити копію зараз')&&!button(dom,'Зробити копію зараз').disabled)
  const file=new dom.window.File(['x'],'large.dump')
  Object.defineProperty(file,'size',{value:200*1024*1024+1})
  const input=dom.window.document.querySelector('input[type=file]')
  Object.defineProperty(input,'files',{value:[file]});input.dispatchEvent(new dom.window.Event('change',{bubbles:true}))
  await waitFor(()=>dom.window.document.body.textContent.includes('Максимум 200 МіБ'))
  assert.equal(writes,0)
 }finally{dom.window.close()}
})
