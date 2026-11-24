// UI-006: every shared Field caption names its control.
import test from 'node:test'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {JSDOM} from 'jsdom'

const root=fileURLToPath(new URL('../',import.meta.url))
const app=`
import React from 'react';import {createRoot} from 'react-dom/client';import {Field} from './src/components/ui';
function Fields(){
  return <>
    <Field label="Назва" hint="Як на вітрині"><input data-case="input" className="input"/></Field>
    <Field label="Статус"><select data-case="select"><option>Новий</option></select></Field>
    <Field label="Опис"><textarea data-case="textarea"/></Field>
    <Field label="Власний id"><input data-case="own-id" id="custom-field"/></Field>
    <Field label="Явний htmlFor" htmlFor="outside"><div><input data-case="explicit" id="outside"/></div></Field>
    <Field label="Ціна" hint="грн"><input data-case="with-button" aria-describedby="price-rule"/><button>Скинути</button></Field>
    <Field label="Промокод" hint="2–32 символи"><div className="promo-code-input"><input data-case="wrapped" aria-label="Промокод"/><button type="button">Згенерувати</button></div></Field>
    <Field label="Перемикач"><label><input data-case="switch" type="checkbox" role="switch" aria-label="Перемикач"/>Увімкнено</label></Field>
    <Field label="Відповідність" hint="Ключ → значення"><div data-case="composite"><input/><input/></div></Field>
  </>
}
createRoot(document.getElementById('root')).render(<Fields/>)`
const bundle=(await build({stdin:{contents:app,resolveDir:root,loader:'jsx'},bundle:true,write:false,format:'iife',jsx:'automatic',loader:{'.css':'empty'},define:{'import.meta.env.VITE_API_URL':'""','process.env.NODE_ENV':'"test"'}})).outputFiles[0].text

async function render(){
  const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true})
  dom.window.eval(bundle)
  const until=Date.now()+3000
  while(!dom.window.document.querySelector('[data-case="composite"]')&&Date.now()<until)await new Promise(r=>setTimeout(r,10))
  return dom
}
const labelOf=(document,control)=>[...document.querySelectorAll('label[for]')].find(label=>label.htmlFor===control.id)

test('a single native control is labelled by the caption and described by the hint',async()=>{
  const dom=await render()
  try{
    const document=dom.window.document
    for(const name of ['input','select','textarea','own-id','with-button','wrapped']){
      const control=document.querySelector(`[data-case="${name}"]`)
      assert.ok(control.id,`${name} has an id`)
      assert.ok(labelOf(document,control),`${name} has a <label for>`)
      assert.equal(control.labels.length,1,`${name} is reachable through control.labels`)
    }
    const input=document.querySelector('[data-case="input"]')
    assert.equal(document.getElementById(input.getAttribute('aria-describedby')).textContent,'Як на вітрині')
    assert.equal(input.labels[0].textContent,'Назва')
  }finally{dom.window.close()}
})

test('ids the caller set and existing descriptions are kept',async()=>{
  const dom=await render()
  try{
    const document=dom.window.document
    assert.equal(document.querySelector('[data-case="own-id"]').id,'custom-field')
    assert.equal(document.querySelector('[data-case="explicit"]').labels[0].textContent,'Явний htmlFor')
    const price=document.querySelector('[data-case="with-button"]')
    const [rule,hint]=price.getAttribute('aria-describedby').split(' ')
    assert.equal(rule,'price-rule')
    assert.equal(document.getElementById(hint).textContent,'грн')
  }finally{dom.window.close()}
})

test('a control wrapped with a helper button is still the labelled control, not a duplicate group',async()=>{
  const dom=await render()
  try{
    const document=dom.window.document
    const input=document.querySelector('[data-case="wrapped"]')
    const field=input.closest('.field')
    assert.equal(field.getAttribute('role'),null)
    assert.equal(input.labels[0].textContent,'Промокод')
    assert.equal(document.getElementById(input.getAttribute('aria-describedby')).textContent,'2–32 символи')
    // A switch inside its own <label> keeps that label; the field caption names the group.
    const toggle=document.querySelector('[data-case="switch"]')
    assert.equal(toggle.labels.length,1)
    assert.equal(toggle.closest('.field').getAttribute('role'),'group')
  }finally{dom.window.close()}
})

test('composite editors become a named, described group',async()=>{
  const dom=await render()
  try{
    const document=dom.window.document
    const field=document.querySelector('[data-case="composite"]').closest('.field')
    assert.equal(field.getAttribute('role'),'group')
    assert.equal(document.getElementById(field.getAttribute('aria-labelledby')).textContent,'Відповідність')
    assert.equal(document.getElementById(field.getAttribute('aria-describedby')).textContent,'Ключ → значення')
    const ids=[...document.querySelectorAll('[id]')].map(node=>node.id)
    assert.equal(new Set(ids).size,ids.length,'generated ids are unique')
  }finally{dom.window.close()}
})
