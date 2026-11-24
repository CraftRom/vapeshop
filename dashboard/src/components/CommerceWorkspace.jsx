import {useCallback,useEffect,useRef,useState} from 'react'
import {Link} from 'react-router-dom'
import {api,isAdmin} from '../api'
import {CHANNELS,channelLabel,phoneHref} from '../commerce'
import {ErrorBar,Loading,dateTime,money} from './ui'
import {useVisiblePolling} from './useVisiblePolling'

function Tile({title,value,to,hint,tone=''}) {
  return <Link className={'commerce-tile '+tone} to={to}><span>{title}</span><strong>{value}</strong><small>{hint} →</small></Link>
}
export default function CommerceWorkspace() {
  const [data,setData]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  const alive=useRef(true),running=useRef(false)
  useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[])
  const load=useCallback(async()=>{
    if(running.current)return
    running.current=true;setBusy(true)
    try{const next=await api.orders.operations();if(alive.current){setData(next);setError('')}}
    catch(error){if(alive.current)setError(error.message)}
    finally{running.current=false;if(alive.current)setBusy(false)}
  },[])
  useVisiblePolling(load,30000,{immediate:true})
  return <section className="commerce-workspace" aria-label="Поточна робота магазину"><header className="commerce-section-head"><div><h2>Робота магазину зараз</h2><p className="faint">Поточна черга й стан товарів, незалежно від періоду фінансового звіту.</p></div><div className="commerce-actions"><button className="btn ghost small" disabled={busy} onClick={load}>{busy?'Оновлюємо…':'Оновити стан'}</button></div></header>
    <ErrorBar error={error}/>{error && data && <p className="faint" role="status">Показані попередні дані від {dateTime(data.generated_at)}.</p>}
    {!data?busy?<Loading rows={3}/>:<p>Не вдалося завантажити стан магазину. <button className="btn ghost small" onClick={load}>Спробувати ще раз</button></p>:<>
      <div className="commerce-tiles"><Tile title="Нові замовлення" value={data.orders.new} to="/orders?queue=new" hint="Перейти до обробки" tone={data.orders.new?'attention':''}/><Tile title="Без накладної" value={data.orders.without_tracking} to="/orders?queue=without_tracking" hint="Перевірити відправлення"/><Tile title="Закінчуються товари" value={data.stock.low} to="/catalog?inventory=low&sort=stock-asc" hint={'Залишок до '+data.low_stock_threshold+' шт.'}/><Tile title="Немає в наявності" value={data.stock.out} to="/catalog?inventory=out" hint="Перевірити залишки"/></div>
      <div className="commerce-columns"><section className="card commerce-queue"><header className="commerce-section-head"><h3>Найстаріші нові замовлення</h3><Link to="/orders?queue=new">Уся черга →</Link></header>{data.queue.length===0?<p className="commerce-empty">Нових замовлень у черзі немає.</p>:<ul>{data.queue.map(order=><li key={order.id}><div><Link to={'/orders/'+order.id} state={{ordersReturn:'/orders?queue=new'}}><strong>#{order.id} · {order.name}</strong></Link><small>{channelLabel(order)} · {dateTime(order.created_at)}</small>{order.phone && <a href={phoneHref(order.phone)}>{order.phone}</a>}</div><strong>{money(order.total)}</strong></li>)}</ul>}</section>
      <section className="card commerce-stock"><header className="commerce-section-head"><h3>Контроль залишків</h3><Link to="/catalog?inventory=low&sort=stock-asc">Усі товари →</Link></header>{data.products.length===0?<p className="commerce-empty">Товарів із малим залишком немає.</p>:<ul>{data.products.map(product=><li key={product.id}><Link to={'/catalog/products/'+product.id} state={{catalogBack:'/catalog?inventory=low&sort=stock-asc'}}><strong>{product.name}</strong></Link><span className="commerce-stock-count">{product.stock} шт.</span></li>)}</ul>}</section></div>
      <footer className="commerce-health"><div className="commerce-channel-links"><span>Відкриті замовлення:</span>{CHANNELS.map(([key,label])=><Link key={key} to={'/orders?queue=open&channel='+key}>{label} <b>{data.channels[key]}</b></Link>)}</div><div className="commerce-readiness"><span>Доступних SKU: <b>{data.stock.available}</b></span><Link to="/catalog?inventory=unpriced">Активні без ціни: <b>{data.stock.unpriced}</b></Link><Link to="/catalog?inventory=missing_photos">Без фото: <b>{data.stock.missing_photos}</b></Link></div><small className="faint">Оновлено {dateTime(data.generated_at)}</small></footer>
    </>}
  </section>
}
