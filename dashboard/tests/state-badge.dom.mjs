// UI-015: states are text + tone + shape; legacy tone names keep working.
import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {JSDOM} from 'jsdom'
import {readSourceCss} from './helpers/source-css.mjs'

const root=fileURLToPath(new URL('../',import.meta.url))
const app=`
import React from 'react';import {createRoot} from 'react-dom/client';import {StateBadge} from './src/components/StateBadge';
createRoot(document.getElementById('root')).render(<>
  <StateBadge tone="success">Працює</StateBadge>
  <StateBadge tone="ok">Активний</StateBadge>
  <StateBadge tone="warn">Не налаштовано</StateBadge>
  <StateBadge tone="bad">Немає виконавця</StateBadge>
  <StateBadge tone="info">Додано</StateBadge>
  <StateBadge tone="">Вимкнено</StateBadge>
  <StateBadge tone="error">Невідомий тон</StateBadge>
  <StateBadge tone="danger" className="inline-badge" title="Причина">прихований</StateBadge>
</>)`
const bundle=(await build({stdin:{contents:app,resolveDir:root,loader:'jsx'},bundle:true,write:false,format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"test"'}})).outputFiles[0].text

test('every tone renders its text, a semantic tone and an aria-hidden shape cue',async()=>{
  const dom=new JSDOM('<div id="root"></div>',{runScripts:'outside-only',pretendToBeVisual:true})
  try{
    dom.window.eval(bundle)
    const until=Date.now()+3000
    while(dom.window.document.querySelectorAll('.state-badge').length<8&&Date.now()<until)await new Promise(r=>setTimeout(r,10))
    const badges=[...dom.window.document.querySelectorAll('.state-badge')]
    const seen=badges.map(b=>[b.dataset.tone,b.className,b.querySelector('.state-badge-glyph')?.textContent||'',b.textContent.replace(b.querySelector('.state-badge-glyph')?.textContent||'','')])
    assert.deepEqual(seen,[
      ['success','chip state-badge ok','✓','Працює'],
      ['success','chip state-badge ok','✓','Активний'],
      ['warning','chip state-badge warn','!','Не налаштовано'],
      ['danger','chip state-badge bad','✕','Немає виконавця'],
      ['info','chip state-badge info','i','Додано'],
      ['neutral','chip state-badge','','Вимкнено'],
      ['neutral','chip state-badge','','Невідомий тон'],
      ['danger','chip state-badge bad inline-badge','✕','прихований'],
    ])
    for(const glyph of dom.window.document.querySelectorAll('.state-badge-glyph'))assert.equal(glyph.getAttribute('aria-hidden'),'true')
    assert.equal(badges.at(-1).title,'Причина')
  }finally{dom.window.close()}
})

test('every chip tone used by the panel has a style, so no state silently looks neutral',()=>{
  const css=readSourceCss()
  const styled=new Set([...css.matchAll(/\.chip\.([a-z-]+)\s*\{/g)].map(m=>m[1]))
  for(const tone of ['ok','warn','bad','info'])assert.ok(styled.has(tone),tone)
  const logs=readFileSync(new URL('../src/pages/Logs.jsx',import.meta.url),'utf8')
  const map=logs.match(/const SEVERITY_CHIP = (\{[^}]+\})/)[1]
  for(const [,tone] of map.matchAll(/:\s*'([^']*)'/g))assert.ok(tone===''||styled.has(tone),`Logs severity tone «${tone}» has no style`)
  assert.match(map,/alarm:\s*'bad'/)
})
