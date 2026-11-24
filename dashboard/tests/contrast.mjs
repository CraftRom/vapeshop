// ELFAR palette guard and contrast report for the production dashboard theme.
//
// The colours are a brand decision: the tests pin the palette and only report
// pairs below WCAG AA (4.5:1) in the log; they never ask to recolour the panel.
//
// The final cascade of every built stylesheet is applied to representative
// markup, var() references are resolved through :root, and each text colour
// is checked against the first opaque background found up the tree.
import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync,readdirSync} from 'node:fs'
import {JSDOM,VirtualConsole} from 'jsdom'

const AA=4.5
const assets=new URL('../dist/assets/',import.meta.url)

function load(markup){
  const names=readdirSync(assets).filter(name=>name.endsWith('.css'))
  assert.ok(names.some(name=>/^index-.*\.css$/.test(name)),'Build dashboard before testing production styles')
  const css=names.map(name=>readFileSync(new URL(name,assets),'utf8')).join('\n')
  const errors=[],virtualConsole=new VirtualConsole()
  virtualConsole.on('jsdomError',error=>errors.push(error.message))
  const dom=new JSDOM(`<!doctype html><style>${css}</style><body>${markup}</body>`,{virtualConsole})
  assert.deepEqual(errors,[])
  return dom
}

function palette(window){
  const root=window.getComputedStyle(window.document.documentElement)
  const resolve=(value,depth=0)=>{
    value=String(value||'').trim()
    assert.ok(depth<10,'var() chain too deep: '+value)
    const ref=value.match(/^var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)$/)
    if(ref)return resolve(root.getPropertyValue(ref[1]).trim()||ref[2]||'',depth+1)
    return value
  }
  const rgba=value=>{
    value=resolve(value).toLowerCase()
    if(!value||value==='transparent'||value==='none')return null
    const hex=value.match(/^#([0-9a-f]{3,8})$/)
    if(hex){
      let h=hex[1];if(h.length<=4)h=[...h].map(c=>c+c).join('')
      const n=h.match(/.{2}/g).map(x=>parseInt(x,16))
      return [n[0],n[1],n[2],n.length>3?n[3]/255:1]
    }
    const fn=value.match(/^rgba?\(([^)]+)\)$/)
    if(fn){const p=fn[1].split(/[\s,/]+/).filter(Boolean).map(Number);return [p[0],p[1],p[2],p.length>3?p[3]:1]}
    return undefined // gradients, images: not a solid colour
  }
  return {resolve,rgba}
}

const luminance=([r,g,b])=>[r,g,b].map(v=>v/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4).reduce((sum,n,i)=>sum+n*[.2126,.7152,.0722][i],0)
const ratio=(a,b)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)}

function pairOf(window,element){
  const {rgba}=palette(window)
  const color=rgba(window.getComputedStyle(element).color)
  assert.ok(color,'text colour must be a solid colour')
  for(let node=element;node&&node.nodeType===1;node=node.parentElement){
    const style=window.getComputedStyle(node)
    for(const value of [style.backgroundColor,style.getPropertyValue('background')]){
      const background=rgba(value)
      assert.notEqual(background,undefined,`background of ${node.className||node.tagName} must be a solid colour: ${value}`)
      if(background&&background[3]>=.99)return {color,background}
    }
  }
  return {color,background:rgba('var(--bg-app)')}
}

const CASES=[
  ['primary button','<main class="card"><button class="btn">Зберегти</button></main>'],
  ['small primary button','<main class="card"><button class="btn small">Додати</button></main>'],
  ['ghost button','<main class="card"><button class="btn ghost">Скасувати</button></main>'],
  ['danger button on a card','<main class="card"><button class="btn danger">Видалити</button></main>'],
  ['active settings tab','<div class="settings-tabs"><button class="btn ghost active">Магазин</button></div>'],
  ['active analytics tab','<div class="tabs"><button class="active">Місяць</button></div>'],
  ['current rail item','<div class="rail"><button class="current">Усі</button></div>'],
  ['current catalog page','<nav><button class="catalog-page-btn active">2</button></nav>'],
  ['active navigation item','<nav class="nav"><a class="active">Замовлення</a></nav>'],
  ['active grouped navigation item','<nav class="nav commerce-navigation"><section class="nav-group"><a class="active">Огляд</a></section></nav>'],
  ['support thread badge','<div class="support-thread-flags"><span class="badge">3</span></div>'],
  ['support client badge','<div class="support-client-counters"><span class="badge">3</span></div>'],
  ['support session badge','<div class="support-session-side"><span class="badge">3</span></div>'],
  ['notification count','<button class="notification-bell has-unread"><span aria-hidden="true">🔔</span><span class="notification-count">5</span></button>'],
  ['secondary hint on a card','<main class="card"><p class="faint">Оновлено щойно</p></main>'],
]

const report=[]
for(const [label,markup] of CASES){
  test(`${label}: text colour resolves on a solid background`,()=>{
    const dom=load(markup)
    try{
      const target=[...dom.window.document.body.querySelectorAll('*')].at(-1)
      const {color,background}=pairOf(dom.window,target)
      const value=ratio(color,background)
      if(value<AA)report.push(`${label}: ${value.toFixed(2)}:1`)
    }finally{dom.window.close()}
  })
}

// The panel looked exactly like this before the tokens were introduced.
const ELFAR={'--bg-app':'#100e18','--surface-1':'#1a1725','--surface-2':'#221e31','--border-strong':'#2e2840',
  '--border-subtle':'#262034','--text-primary':'#ece9f5','--text-secondary':'#948cad','--text-tertiary':'#635b7d',
  '--action-primary-bg':'#8b7bf0','--action-primary-fg':'#ffffff','--action-selected-bg':'#5f51b8',
  '--action-selected-fg':'#ffffff','--status-success':'#4fd8a5','--status-warning':'#f2b347',
  '--status-danger':'#f2607e','--on-status-fg':'#ffffff'}

test('tokens keep the ELFAR palette unchanged',()=>{
  const dom=load('')
  try{
    const root=dom.window.getComputedStyle(dom.window.document.documentElement)
    const actual=Object.fromEntries(Object.keys(ELFAR).map(name=>[name,root.getPropertyValue(name).trim().toLowerCase()]))
    assert.deepEqual(actual,ELFAR)
  }finally{dom.window.close()}
})

test('contrast report',()=>{
  // Known ELFAR pairs below 4.5:1 (e.g. white on the violet button) are listed, not failed.
  if(report.length)console.log('# below WCAG AA (palette kept by design): '+report.join('; '))
})
