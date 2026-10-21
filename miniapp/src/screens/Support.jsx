import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api } from '../api'
import { ChatRoom } from './Chat'

export function SupportCenter({ rooms, onBack, backRef }) {
  const [threads,setThreads]=useState(null), [selected,setSelected]=useState(null)
  const [error,setError]=useState(''), [busy,setBusy]=useState(false), [more,setMore]=useState(false)
  const alive=useRef(true), action=useRef(false), generation=useRef(0)
  const load=useCallback(async(older=false)=>{
    const request=++generation.current
    try {
      const result=await api.support.list(older?threads?.at(-1)?.id:null)
      if(!alive.current || request!==generation.current)return
      setThreads(current=>older?[...(current||[]),...result.items.filter(x=>!current?.some(y=>x.id===y.id))]:result.items)
      setMore(result.has_more);setError('')
    } catch(err){if(alive.current && request===generation.current)setError(err.message)}
  },[threads])
  useEffect(()=>{alive.current=true;load();return()=>{alive.current=false;generation.current++}},[])
  useLayoutEffect(()=>{
    if(backRef)backRef.current=()=>{if(selected){setSelected(null);load()}else onBack()}
    return()=>{if(backRef)backRef.current=null}
  },[selected,load,onBack,backRef])
  const start=async()=>{
    if(action.current)return
    action.current=true;setBusy(true);setError('')
    try{const thread=await api.support.start();if(alive.current)setSelected(thread)}
    catch(err){if(alive.current)setError(err.message)}
    finally{action.current=false;if(alive.current)setBusy(false)}
  }
  if(selected){
    if(!rooms.has(selected.id))rooms.set(selected.id,{text:'',revision:0,listeners:new Set()})
    return <ChatRoom key={`support:${selected.id}`} config={{}} order={{...selected,can_chat:selected.status==='open'}} support
      draft={rooms.get(selected.id)} onBack={()=>{setSelected(null);load()}} />
  }
  return <section className="support-center">
    <div className="head"><button className="back" onClick={onBack}>Чати замовлень</button><h1>Загальна підтримка</h1>
      <p>Питання про магазин, оплату чи роботу застосунку. Звернення також доступні в боті.</p></div>
    {error&&<div className="banner warn" role="alert">{error} <button className="secondary" onClick={()=>load()}>Повторити</button></div>}
    <button className="primary" onClick={start} disabled={busy}>{busy?'Відкриваємо…':'Написати в підтримку'}</button>
    {threads===null&&!error?<div className="skeleton skeleton-line"/>:threads?.length===0?<p className="hint">Звернень поки немає. Напишіть нам — менеджер відповість тут.</p>:null}
    {threads?.map(thread=><button className="order chat-pick" key={thread.id} onClick={()=>setSelected(thread)}>
      <div className="order-head"><strong>Звернення №{thread.id}</strong><span>{thread.status==='open'?'Відкрите':'Завершене'}</span></div>
      <span className="hint">{thread.created_at?new Date(thread.created_at).toLocaleString('uk-UA'):''}</span>
    </button>)}
    {more&&<button className="secondary" disabled={busy} onClick={()=>load(true)}>Раніші звернення</button>}
  </section>
}
