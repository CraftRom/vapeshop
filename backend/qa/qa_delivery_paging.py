"""Isolated provider contract tests (no database, credentials, network required)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shop.services import novaposhta as np

CITY = [{"Ref": f"settlement-{i}", "DeliveryCity": f"city-{i}",
         "Present": f"с. Миколаївка ({i}), Одеська обл.",
         "MainDescription": "Миколаївка", "Warehouses": 1} for i in range(97)]
WH = [{"Ref": f"warehouse-{i}", "Number": str(i),
       "Description": f"Відділення №{i}: вул. Широка, {i}",
       "ShortAddress": f"Широка, {i}", "CategoryOfWarehouse": "Branch"} for i in range(1, 141)]
requests = []
blocked = False

async def fake_post(payload):
    global blocked
    requests.append(payload)
    if blocked:
        raise np.httpx.ConnectError("fake disconnection")
    method = payload['calledMethod']
    props = payload['methodProperties']
    page, limit = int(props.get('Page', 1)), int(props.get('Limit', 20))
    if method == 'searchSettlements':
        return {'success': True, 'data': [{
            'TotalCount': len(CITY),
            'Addresses': CITY[(page-1)*limit:page*limit],
        }]}
    if method == 'getWarehouses':
        q = props.get('FindByString', '') or props.get('WarehouseId', '')
        filtered = ([w for w in WH if int(w['Number']) == int(q)]
                    if q.isdecimal() else [w for w in WH if q.casefold() in w['Description'].casefold()])
        return {'success': True, 'data': filtered[(page-1)*limit:page*limit]}
    if method == 'searchSettlementStreets':
        return {'success': True, 'data': [{'TotalCount': 1, 'Addresses': [
            {'Ref': 'street-1', 'SettlementStreetDescription': 'Широка'}]}]}
    raise AssertionError(method)

async def main():
    global blocked
    np._post = fake_post
    np.reset_cache()
    key='qa-secret'
    found = []
    for page in range(1, 7):
        response = await np.search_settlements(key, 'Миколаївка', page=page, return_meta=True)
        found.extend(response['items'])
        assert response['has_more'] == (page < 5), (page, response['has_more'])
    assert len({x.settlement_ref for x in found}) == 97, len(found)
    print('PASS 97 city variants / pagination')

    np.reset_cache()
    for page in (1, 2, 3):
        response = await np.warehouses(key, 'city-ref', 'settlement-ref', page=page, return_meta=True)
        assert len(response['items']) == (50 if page < 3 else 40)
    assert len(requests) == 9
    print('PASS warehouse pages 50/50/40')

    np.reset_cache()
    found = await np.warehouses(key, 'city-ref', query='139')
    assert len(found) == 1 and found[0].number == 139
    found = await np.warehouses(key, 'city-ref', query='Широка', page=3)
    assert len(found) == 40 and found[-1].number == 140
    print('PASS provider-side number / street search (beyond first 50)')

    streets = await np.search_streets(key, 'settlement-ref', 'Шир')
    assert streets['items'][0]['name'] == 'Широка'
    print('PASS courier street suggestions')

    blocked=True
    np.reset_cache()
    try:
        await np.warehouses(key, 'city-ref')
        raise AssertionError('provider failure hidden as empty list')
    except np.NovaPoshtaError:
        print('PASS network error is not no-results')
    print('DELIVERY CATALOG QA PASS')

if __name__=='__main__':
    asyncio.run(main())
