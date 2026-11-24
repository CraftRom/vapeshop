import test from 'node:test'
import assert from 'node:assert/strict'
import {recipientName,customerContact,customerName,customerSubtitle,paymentMeta,orderChannel,inventoryState,publicationState,navigationFor} from '../src/commerce.js'

test('recipient names support both normalized full names and older split fields',()=>{
 assert.equal(recipientName({contact_surname:'Покупець',contact_name:'Покупець Дмитро Іванович',contact_patronymic:'Іванович'}),'Покупець Дмитро Іванович')
 assert.equal(recipientName({contact_surname:'Покупець',contact_name:'Дмитро',contact_patronymic:'Іванович'}),'Покупець Дмитро Іванович')
 assert.equal(recipientName({contact_name:' Дмитро  Іванович ',contact_patronymic:'Іванович'}),'Дмитро Іванович')
})
test('missing contacts and payment methods never masquerade as Telegram or card payment',()=>{
 assert.equal(customerContact({}),'Контакт не вказано')
 assert.equal(customerContact({tg_id:123,username:'realname'}),'@realname')
 assert.match(paymentMeta(null).title,/не вказано/)
})
test('customer names come from Telegram, never a placeholder id',()=>{
 assert.equal(customerName({tg_id:5,first_name:'Тарас'}),'Тарас')
 assert.equal(customerName({tg_id:5}),'Без імені')
 assert.equal(customerSubtitle({id:5,tg_id:55,username:'taras',phone:'+380671234567'}),'@taras · +380671234567')
 assert.equal(customerSubtitle({id:5,tg_id:55}),'Telegram 55')
})
test('campaign source does not override the actual sales channel',()=>{
 assert.equal(orderChannel({attribution:{source:'google',channel:'telegram_bot'}}),'bot')
 assert.equal(orderChannel({attribution:{source:'telegram_bot'}}),'bot')
 assert.equal(orderChannel({attribution:{source:'google',session_id:'miniapp-session'}}),'miniapp')
 assert.equal(orderChannel({attribution:{source:'telegram_bot',channel:'telegram_miniapp'}}),'miniapp')
 assert.equal(orderChannel({attribution:{source:'unknown'}}),'unknown')
})
test('stock states match sellable products instead of active flags alone',()=>{
 assert.match(inventoryState({is_active:true,price:0,stock:20}).label,/Без ціни/)
 assert.equal(inventoryState({is_active:true,price:100,stock:3}).tone,'warn')
 assert.equal(inventoryState({is_active:false,price:100,stock:3}).tone,'hidden')
 assert.equal(publicationState({name:'Товар',is_active:true,price:0,stock:20}).visible,false)
 assert.deepEqual(publicationState({name:'Товар',is_active:true,price:100,stock:0}),{visible:true,buyable:false,label:'У магазині, немає в наявності'})
})
test('grouped commerce navigation preserves role boundaries',()=>{
 const manager=navigationFor('operator').flatMap(group=>group.items).map(item=>item.to)
 assert.ok(manager.includes('/orders') && manager.includes('/catalog'))
 for(const path of ['/operators','/backups','/logs'])assert.ok(!manager.includes(path),path)
 assert.ok(navigationFor('shop_admin').flatMap(group=>group.items).some(item=>item.to==='/operators'))
 assert.ok(!navigationFor('shop_admin').flatMap(group=>group.items).some(item=>item.to==='/logs'))
 assert.deepEqual(navigationFor('unknown'),[])
})
