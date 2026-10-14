import { useEffect, useRef } from 'react'
import { money } from '../money'
import { StoreIcon } from '../StoreIcon'

export function OrderSuccess({ order, onCatalog, onOrders, onChat }) {
  const heading = useRef(null)
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' }); heading.current?.focus({ preventScroll: true }) }, [])
  return <section className="order-success" aria-labelledby="order-success-title">
    <div className="order-success-mark" aria-hidden="true"><StoreIcon name="check" /></div>
    <h1 id="order-success-title" ref={heading} tabIndex={-1}>Замовлення №{order.order_id} прийнято</h1>
    <p>Замовлення збережене. Менеджер зв’яжеться з вами в Telegram.</p>
    <dl className="order-success-details">
      <div><dt>До сплати</dt><dd className="num">{money(order.total)} {order.currency}</dd></div>
      <div><dt>Спосіб оплати</dt><dd>{order.payment_method === 'cod' ? 'Накладений платіж' : 'Переказ на картку'}</dd></div>
    </dl>
    <p className="hint">{order.payment_method === 'cod' ? 'Оплата при отриманні. Доставку та комісію перевізника сплачуєте окремо.' : Number(order.total) > 0 ? 'Менеджер надішле реквізити у чат. Після оплати надішліть квитанцію боту як фото або документ.' : 'Додаткова оплата товарів не потрібна. Умови доставки уточнить менеджер.'}</p>
    <div className="actions order-success-actions">
      <button className="primary" onClick={onChat}>Чат замовлення</button>
      <button className="secondary" onClick={onOrders}>Мої замовлення</button>
      <button className="secondary" onClick={onCatalog}>Продовжити покупки</button>
    </div>
  </section>
}
