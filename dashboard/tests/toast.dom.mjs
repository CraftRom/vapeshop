// UI-025: success fades, errors stay until closed and interrupt as alerts.
import test from 'node:test'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {JSDOM} from 'jsdom'

const root=fileURLToPath(new URL('../',import.meta.url))
const app=`
import React from 'react';import {createRoot} from 'react-dom/client';import {ToastProvider,useToast} from './src/components/ui';
function Buttons(){const notify=useToast();return <>
 <button data-ok onClick={()=>notify('Збережено')}>ok</button>
 <button data-bad onClick={()=>notify('Не вдалося зберегти','bad')}>bad</button>
 <button data-warn onClick={()=>notify('Перевірте ключ','warning')}>warn</button>
</>}
createRoot(document.getElementById('root')).render(<ToastProvider><Buttons/></ToastProvider>)`
const bundle=(await build({stdin:{contents:app,resolveDir:root,loader:'jsx'},bundle:true,write:false,format:'iife',jsx:'automatic',loader:{'.css':'empty'},define:{'process.env.NODE_ENV':'"test"'}})).outputFiles[0].text

async function render(){
  const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true})
  dom.window.eval(bundle)
  const until=Date.now()+3000
  while(!dom.window.document.querySelector('[data-ok]')&&Date.now()<until)await new Promise(r=>setTimeout(r,10))
  return dom
}
const tick=(ms=20)=>new Promise(r=>setTimeout(r,ms))

test('success is a polite status with a shape cue and a close button',async()=>{
  const dom=await render()
  try{
    const doc=dom.window.document
    doc.querySelector('[data-ok]').click();await tick()
    const toast=doc.querySelector('.toast')
    assert.equal(toast.getAttribute('role'),'status')
    assert.equal(toast.className,'toast ok')
    assert.equal(toast.querySelector('.toast-glyph').getAttribute('aria-hidden'),'true')
    assert.equal(toast.querySelector('.toast-message').textContent,'Збережено','message element holds exactly the message')
    assert.equal(toast.querySelector('.sr-only').textContent,'Готово: ')
    toast.querySelector('.toast-close').click();await tick()
    assert.equal(doc.querySelector('.toast'),null)
  }finally{dom.window.close()}
})

test('an error is an alert and does not disappear on its own',async()=>{
  const dom=await render()
  try{
    const doc=dom.window.document
    doc.querySelector('[data-bad]').click();await tick()
    assert.equal(doc.querySelector('.toast').getAttribute('role'),'alert')
    assert.match(doc.querySelector('.toast').textContent,/Помилка: Не вдалося зберегти/)
    await tick(3600) // longer than a success message lives
    assert.ok(doc.querySelector('.toast.bad'),'error is still visible')
  }finally{dom.window.close()}
})

test('semantic aliases map to the panel kinds',async()=>{
  const dom=await render()
  try{
    dom.window.document.querySelector('[data-warn]').click();await tick()
    assert.equal(dom.window.document.querySelector('.toast').className,'toast warn')
  }finally{dom.window.close()}
})
