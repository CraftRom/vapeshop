// Оновлення переліку списків у застосунку.
//
// Логіка виглядає дрібницею, але саме на ній зламалось усе «Збережене»:
// створений список не потрапляв у стан, тому його не було ні у виборі,
// ні на екрані, а повторна спроба створити ту саму назву давала 409.
import { readFileSync } from 'node:fs'

const src = readFileSync('src/App.jsx', 'utf8')
const start = src.indexOf('const onWishlistChanged')
const end = src.indexOf('}, [])', start) + 6
const body = src.slice(start, end)

// Підміняємо гачки React на прості функції: нас цікавить рішення
// «додати чи підмінити», а не рендер.
let state = []
const setWishlists = (fn) => { state = typeof fn === 'function' ? fn(state) : fn }
const api = { wishlists: { list: async () => state } }
const useCallback = (fn) => fn
const handler = new Function(
  'setWishlists', 'api', 'useCallback',
  body + '\nreturn onWishlistChanged',
)(setWishlists, api, useCallback)

let bad = 0
const eq = (got, want, label) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) bad++
  console.log(`  ${ok ? '✓' : '✗'} ${label}${ok ? '' : ` — ${JSON.stringify(got)}`}`)
}

console.log('\n--- створення ---')
state = [{ id: 1, name: 'Обране', items: [] }]
handler({ id: 2, name: 'Подарунки', items: [] })
eq(state.map((w) => w.id), [1, 2], 'новий список додано в перелік')

console.log('\n--- зміна наявного ---')
handler({ id: 2, name: 'Подарунки', items: [{ product_id: 7 }] })
eq(state.length, 2, 'кількість не змінилась')
eq(state[1].items.length, 1, 'вміст оновлено')

console.log('\n--- перейменування ---')
handler({ id: 1, name: 'Хочу собі', items: [] })
eq(state[0].name, 'Хочу собі', 'назва оновлена на місці')

console.log('\n--- повторне створення того самого id ---')
handler({ id: 2, name: 'Подарунки', items: [] })
eq(state.length, 2, 'дубля не з\u2019явилось')

console.log(`\nСТАН СПИСКІВ: ${bad === 0 ? 'усе витримано' : `ПРОВАЛЕНО: ${bad}`}`)
process.exit(bad ? 1 : 0)
