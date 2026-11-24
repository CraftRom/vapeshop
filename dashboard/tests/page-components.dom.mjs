// UI-007: shared page structure — header, titled sections, filter bars.
import test from 'node:test'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {JSDOM} from 'jsdom'

const root=fileURLToPath(new URL('../',import.meta.url))
const app=`
import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import {MemoryRouter} from 'react-router-dom';import {FilterBar,PageHeader,SectionCard} from './src/components/page';
function Page(){
  const [search,setSearch]=useState('')
  return <>
    <PageHeader title="Клієнти" description="Історія покупок" actions={<button>Новий</button>}/>
    <PageHeader title="Без опису" className="extra"/>
    <PageHeader title="З довідкою" description="Опис" help="orders"/>
    <SectionCard title="Telegram" description="Бот і групи" actions={<label><input type="checkbox" role="switch" aria-label="Telegram"/>Увімкнено</label>}><p data-body="1">Поля</p></SectionCard>
    <SectionCard title="Підсекція" level={3}><p>Текст</p></SectionCard>
    <FilterBar label="Пошук клієнтів" activeCount={search?1:0} onReset={()=>setSearch('')}>
      <input aria-label="Пошук" value={search} onChange={e=>setSearch(e.target.value)} data-search="1"/>
    </FilterBar>
    <button data-fill="1" onClick={()=>setSearch('Олена')}>fill</button>
  </>
}
createRoot(document.getElementById('root')).render(<MemoryRouter><Page/></MemoryRouter>)`
const bundle=(await build({stdin:{contents:app,resolveDir:root,loader:'jsx'},bundle:true,write:false,format:'iife',jsx:'automatic',loader:{'.css':'empty'},define:{'process.env.NODE_ENV':'"test"'}})).outputFiles[0].text

async function render(){
  const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true})
  dom.window.eval(bundle)
  const until=Date.now()+3000
  while(!dom.window.document.querySelector('[data-fill]')&&Date.now()<until)await new Promise(r=>setTimeout(r,10))
  return dom
}
const tick=()=>new Promise(r=>setTimeout(r,20))

test('PageHeader renders one h1 with its context and actions inside the page-head',async()=>{
  const dom=await render()
  try{
    const [first,second]=dom.window.document.querySelectorAll('header.page-head')
    assert.equal(first.querySelector('h1').textContent,'Клієнти')
    assert.equal(first.querySelector('p').textContent,'Історія покупок')
    assert.equal(first.querySelector('button').textContent,'Новий')
    assert.equal(second.className,'page-head extra')
    assert.equal(second.querySelector('p'),null,'no empty description paragraph')
    const help=dom.window.document.querySelectorAll('header.page-head')[2].querySelector('a.help-link')
    assert.equal(help.getAttribute('href'),'/instructions?topic=orders')
    assert.equal(help.textContent,'Як це працює →')
  }finally{dom.window.close()}
})

test('SectionCard is a region named by its heading, with actions on the heading row',async()=>{
  const dom=await render()
  try{
    const document=dom.window.document
    const [main,sub]=document.querySelectorAll('section.card.section-card')
    assert.equal(document.getElementById(main.getAttribute('aria-labelledby')).textContent,'Telegram')
    assert.equal(main.querySelector('.section-card-head > h2').textContent,'Telegram')
    assert.ok(main.querySelector('.section-card-head [role="switch"]'))
    assert.equal(main.querySelector('.section-card-description').textContent,'Бот і групи')
    assert.ok(main.querySelector('[data-body]'))
    assert.equal(sub.querySelector('.section-card-head > h3').textContent,'Підсекція')
    assert.equal(sub.querySelector('.section-card-description'),null)
  }finally{dom.window.close()}
})

test('FilterBar is a named group whose reset appears only while something is filtered',async()=>{
  const dom=await render()
  try{
    const document=dom.window.document
    const bar=document.querySelector('.filter-bar')
    assert.equal(bar.getAttribute('role'),'group')
    assert.equal(bar.getAttribute('aria-label'),'Пошук клієнтів')
    assert.equal(bar.querySelector('.filter-bar-reset'),null)
    document.querySelector('[data-fill]').click();await tick()
    const reset=bar.querySelector('.filter-bar-reset')
    assert.equal(reset.textContent,'Скинути фільтри (1)')
    assert.equal(reset.type,'button')
    reset.click();await tick()
    assert.equal(document.querySelector('[data-search]').value,'')
    assert.equal(bar.querySelector('.filter-bar-reset'),null)
  }finally{dom.window.close()}
})
