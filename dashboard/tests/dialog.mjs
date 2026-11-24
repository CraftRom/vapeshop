import test from 'node:test'
import assert from 'node:assert/strict'
import {JSDOM} from 'jsdom'

for(const [label,path] of [['dashboard','../src/components/dialog.js']]) {
 const {mountDialog}=await import(path)
 function setup(){
  const dom=new JSDOM('<!doctype html><body style="overflow:auto"><button id="outside">Відкрити</button><section id="outer" tabindex="-1"><fieldset disabled><input id="blocked"></fieldset><button id="first">Перший</button><button id="last">Останній</button></section><section id="inner" tabindex="-1"><button id="inside">Усередині</button></section></body>',{pretendToBeVisual:true})
  globalThis.document=dom.window.document;globalThis.getComputedStyle=dom.window.getComputedStyle.bind(dom.window)
  dom.window.HTMLElement.prototype.getClientRects=function(){return this.hidden?[]:[{}]}
  const node=id=>dom.window.document.getElementById(id)
  node('outside').focus()
  return {dom,node,key:(key,shiftKey=false)=>{const event=new dom.window.KeyboardEvent('keydown',{key,shiftKey,bubbles:true,cancelable:true});document.dispatchEvent(event);return event},close:()=>{dom.window.close();delete globalThis.document;delete globalThis.getComputedStyle}}
 }
 test(label+': disabled fieldsets are skipped and keyboard focus wraps inside the dialog',()=>{
  const app=setup();const dispose=mountDialog(app.node('outer'),()=>{})
  try{
   assert.equal(document.activeElement.id,'first')
   app.node('last').focus();assert.ok(app.key('Tab').defaultPrevented);assert.equal(document.activeElement.id,'first')
   app.key('Tab',true);assert.equal(document.activeElement.id,'last')
   app.node('outside').focus();assert.equal(document.activeElement.id,'first')
  }finally{dispose();app.close()}
 })
 test(label+': Escape closes only the foreground dialog and restores focus and scrolling',()=>{
  const app=setup();let outerClosed=0,innerClosed=0,closeOuter,closeInner
  closeOuter=mountDialog(app.node('outer'),()=>{outerClosed++;closeOuter()})
  closeInner=mountDialog(app.node('inner'),()=>{innerClosed++;closeInner()})
  try{
   app.key('Escape');assert.equal(innerClosed,1);assert.equal(outerClosed,0);assert.equal(document.activeElement.id,'first');assert.equal(document.body.style.overflow,'hidden')
   app.key('Escape');assert.equal(outerClosed,1);assert.equal(document.activeElement.id,'outside');assert.equal(document.body.style.overflow,'auto')
  }finally{closeInner();closeOuter();app.close()}
 })
 test(label+': out-of-order and repeated cleanup does not unlock or steal focus from another dialog',()=>{
  const app=setup(),closeOuter=mountDialog(app.node('outer'),()=>{}),closeInner=mountDialog(app.node('inner'),()=>{})
  try{
   closeOuter();closeOuter();assert.equal(document.body.style.overflow,'hidden');assert.equal(document.activeElement.id,'inside')
   closeInner();assert.equal(document.body.style.overflow,'auto')
   const closeAgain=mountDialog(app.node('outer'),()=>{});assert.equal(document.body.style.overflow,'hidden');closeAgain();assert.equal(document.body.style.overflow,'auto')
  }finally{closeInner();closeOuter();app.close()}
 })
}
