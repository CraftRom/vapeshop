// UI-016: column personalisation keyed by stable ids, not header captions.
import test from 'node:test'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {JSDOM} from 'jsdom'

const root=fileURLToPath(new URL('../',import.meta.url))
const app=`
import React from 'react';import {createRoot} from 'react-dom/client';import {ManagedTable} from './src/components/ManagedTable';
const caption=window.testCaption||'ROAS'
createRoot(document.getElementById('root')).render(
 <ManagedTable tableId="t" label="Тест"><table>
  <thead><tr><th>Назва</th><th>Сума</th><th>Сума</th><th data-column="roas">{caption}</th></tr></thead>
  <tbody><tr><td>a</td><td>1</td><td>2</td><td>3</td></tr></tbody>
 </table></ManagedTable>)`
const bundle=(await build({stdin:{contents:app,resolveDir:root,loader:'jsx'},bundle:true,write:false,format:'iife',jsx:'automatic',loader:{'.css':'empty'},define:{'process.env.NODE_ENV':'"test"'}})).outputFiles[0].text

async function render(storage={},caption){
  const dom=new JSDOM('<div id="root"></div>',{url:'https://dashboard.test/',runScripts:'outside-only',pretendToBeVisual:true})
  for(const [key,value] of Object.entries(storage))dom.window.localStorage.setItem(key,value)
  if(caption)dom.window.testCaption=caption
  dom.window.eval(bundle)
  const until=Date.now()+3000
  while(!dom.window.document.querySelector('td')&&Date.now()<until)await new Promise(r=>setTimeout(r,10))
  return dom
}
const hiddenCells=dom=>[...dom.window.document.querySelectorAll('tbody td')].map(td=>td.hidden)
const openColumns=async dom=>{[...dom.window.document.querySelectorAll('button')].find(b=>b.textContent==='Колонки: Тест').click();await new Promise(r=>setTimeout(r,20));return [...dom.window.document.querySelectorAll('.table-column-options input')]}

test('two columns with the same caption are hidden independently',async()=>{
  const dom=await render()
  try{
    const boxes=await openColumns(dom)
    assert.equal(boxes.length,4)
    boxes[2].click();await new Promise(r=>setTimeout(r,20))
    assert.deepEqual(hiddenCells(dom),[false,false,true,false])
    assert.deepEqual(JSON.parse(dom.window.localStorage.getItem('elfar.table.columns.v2.t')),['Сума#2'])
  }finally{dom.window.close()}
})

test('a saved choice follows the data-column id when the caption changes',async()=>{
  const dom=await render({'elfar.table.columns.v2.t':JSON.stringify(['roas'])},'Окупність реклами')
  try{assert.deepEqual(hiddenCells(dom),[false,false,false,true])}finally{dom.window.close()}
})

test('caption-based choices from the old elfar.* key are migrated once',async()=>{
  const dom=await render({'elfar.table.columns.t':JSON.stringify(['ROAS','Назва'])})
  try{
    // The identity column can never be hidden, even if an old value says so.
    assert.deepEqual(hiddenCells(dom),[false,false,false,true])
    assert.equal(dom.window.localStorage.getItem('elfar.table.columns.t'),null)
    assert.deepEqual(JSON.parse(dom.window.localStorage.getItem('elfar.table.columns.v2.t')),['Назва','roas'])
  }finally{dom.window.close()}
})

test('broken stored values fall back to showing every column',async()=>{
  const dom=await render({'elfar.table.columns.v2.t':'{not json'})
  try{assert.deepEqual(hiddenCells(dom),[false,false,false,false])}finally{dom.window.close()}
})
