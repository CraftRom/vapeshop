"""Read-only operational queues shared by dashboard counts and order filters."""
from datetime import datetime,timezone
from sqlalchemy import select,func,case,and_,or_
from shop import models as m
from shop.entities import OrderStatus

OPEN=(OrderStatus.NEW,OrderStatus.ACCEPTED,OrderStatus.PAID,OrderStatus.SHIPPED)

def channel_expression():
    raw_source=func.lower(func.trim(func.coalesce(m.Order.attribution['source'].as_string(),'')))
    crm_source=func.lower(func.trim(func.coalesce(m.Order.crm_snapshot['utm']['source'].as_string(),'')))
    source=case((raw_source.in_(['','unknown']),crm_source),else_=raw_source)
    channel=func.coalesce(m.Order.attribution['channel'].as_string(),'')
    session=func.coalesce(m.Order.attribution['session_id'].as_string(),'')
    return case(
        (channel=='telegram_bot','bot'),(channel=='telegram_miniapp','miniapp'),
        (source=='telegram_bot','bot'),
        (or_(source.in_(['telegram','miniapp','telegram_miniapp']),session!=''),'miniapp'),
        else_='unknown')

def queue_condition(queue):
    active=and_(m.Order.status.in_(OPEN),m.Order.business_state.notin_(['refusal','return']))
    if queue=='new':return and_(active,m.Order.status==OrderStatus.NEW)
    if queue=='without_tracking':return and_(active,m.Order.status.in_([OrderStatus.NEW,OrderStatus.ACCEPTED,OrderStatus.PAID]),func.trim(func.coalesce(m.Order.tracking_number,''))=='')
    return active

def aware(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value

async def workspace(repo,*,low_stock=3):
    def count_if(condition):return func.coalesce(func.sum(case((condition,1),else_=0)),0)
    orders=(await repo.s.execute(select(
        count_if(queue_condition('new')).label('new'),
        count_if(queue_condition('open')).label('open'),
        count_if(queue_condition('without_tracking')).label('without_tracking')))).mappings().one()
    channel=channel_expression()
    channels=dict((await repo.s.execute(select(channel,func.count()).where(queue_condition('open')).group_by(channel))).all())
    sellable=and_(m.Product.is_active.is_(True),m.Product.price>0,func.trim(m.Product.name)!='')
    photos=and_(func.trim(func.coalesce(m.Product.photo_url,''))=='',func.trim(func.coalesce(m.Product.photo_file_id,''))=='')
    stock=(await repo.s.execute(select(
        count_if(and_(sellable,m.Product.stock>0)).label('available'),
        count_if(and_(sellable,m.Product.stock>0,m.Product.stock<=low_stock)).label('low'),
        count_if(and_(sellable,m.Product.stock<=0)).label('out'),
        count_if(and_(m.Product.is_active.is_(True),m.Product.price<=0)).label('unpriced'),
        count_if(and_(sellable,photos)).label('missing_photos')))).mappings().one()
    pending=(await repo.s.scalars(select(m.Order).where(queue_condition('new')).order_by(m.Order.created_at,m.Order.id).limit(6))).all()
    products=(await repo.s.scalars(select(m.Product).where(sellable,m.Product.stock>0,m.Product.stock<=low_stock).order_by(m.Product.stock,m.Product.id).limit(8))).all()
    result={'generated_at':datetime.now(timezone.utc),'orders':dict(orders),'channels':{key:int(channels.get(key,0)) for key in ['miniapp','bot','unknown']},
        'stock':dict(stock),'low_stock_threshold':low_stock,
        'queue':[{'id':row.id,'name':row.contact_name or 'Покупець','phone':row.contact_phone or '',
            'total':str(row.total),'status':row.status.value,'created_at':aware(row.created_at),
            'attribution':{key:(row.attribution or {}).get(key,'') for key in ['source','channel','session_id']}} for row in pending],
        'products':[{'id':row.id,'name':row.name,'stock':row.stock,'price':str(row.price)} for row in products]}
    return result
