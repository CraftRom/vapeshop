import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync,readdirSync} from 'node:fs'
import {JSDOM,VirtualConsole} from 'jsdom'

test('production CSS keeps navigation text dark after all base styles are applied',()=>{
 const assets=new URL('../dist/assets/',import.meta.url)
 const file=readdirSync(assets).find(name=>/^index-.*\.css$/.test(name))
 assert.ok(file,'Build dashboard before testing production styles')
 const css=readFileSync(new URL(file,assets),'utf8')
 const errors=[],virtualConsole=new VirtualConsole()
 virtualConsole.on('jsdomError',error=>errors.push(error.message))
 const dom=new JSDOM('<!doctype html><style>'+css+'</style><nav class="nav commerce-navigation"><section class="nav-group"><a class="active">Огляд магазину</a></section></nav>',{virtualConsole})
 try{
  assert.deepEqual(errors,[])
  assert.equal(dom.window.getComputedStyle(dom.window.document.querySelector('a')).color,'rgb(25, 21, 15)')
 }finally{dom.window.close()}
})
