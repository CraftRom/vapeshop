import assert from 'node:assert/strict'
const data=new Map()
globalThis.sessionStorage={get length(){return data.size},key:i=>[...data.keys()][i]??null,getItem:key=>data.get(key)||null,setItem:(key,v)=>data.set(key,v),removeItem:key=>data.delete(key)}
globalThis.window={Telegram:{WebApp:{initData:'user=%7B%22id%22%3A1%7D&auth_date=1&hash=qa'}}}
const {supportRequest,confirmSupportRequest,clearSupportRequests}=await import('../src/supportRequests.js')
let checks=0
const check=(ok,label)=>{assert.ok(ok,label);checks++;console.log('PASS '+label)}
const first=supportRequest(7,'Same text')
check(supportRequest(7,'Same text').request_id===first.request_id,'unknown result reuses request key')
check(supportRequest(8,'Same text').request_id!==first.request_id,'different threads use different request keys')
const next=supportRequest(7,'New text')
confirmSupportRequest(7,first.request_id)
check(supportRequest(7,'New text').request_id===next.request_id,'late confirmation cannot delete new attempt')
confirmSupportRequest(7,next.request_id)
check(supportRequest(7,'New text').request_id!==next.request_id,'same intended text after acknowledgement is a new message')
window.Telegram.WebApp.initData='user=%7B%22id%22%3A2%7D&auth_date=1&hash=qa'
check(supportRequest(7,'Same text').request_id!==first.request_id,'different Telegram accounts cannot reuse another attempt')
clearSupportRequests()
check(data.size===0,'auth invalidation removes stored attempts')
console.log(`SUPPORT REQUESTS: ${checks}/${checks}`)
