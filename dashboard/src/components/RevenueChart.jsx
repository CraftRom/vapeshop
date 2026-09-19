import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

import { money } from './ui'

/**
 * Два фінансові шари на одному графіку:
 * confirmed — підтверджений оборот; revenue — кошти, які вже можна вважати
 * отриманими. Так COD після відправки не малюється як гроші на рахунку.
 */
export default function RevenueChart({ data }) {
  return (
    <div style={{ height: 280, marginTop: 14 }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
          <defs>
            <linearGradient id="received" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#66d9b8" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#66d9b8" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="turnover" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#8b7bf0" stopOpacity={0.2} />
              <stop offset="100%" stopColor="#8b7bf0" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#2e2840" vertical={false} />
          <XAxis
            dataKey="date"
            stroke="#635b7d"
            fontSize={11}
            tickFormatter={(v) => v.slice(5).replace('-', '.')}
          />
          <YAxis stroke="#635b7d" fontSize={11} />
          <Tooltip
            contentStyle={{
              background: '#221e31', border: '1px solid #2e2840', borderRadius: 10, color: '#ece9f5',
            }}
            formatter={(value, name) => {
              if (name === 'confirmed') return [money(value), 'Підтверджений оборот']
              if (name === 'revenue') return [money(value), 'Отримано']
              return [value, name]
            }}
          />
          <Area type="monotone" dataKey="confirmed" stroke="#8b7bf0" strokeWidth={2} fill="url(#turnover)" />
          <Area type="monotone" dataKey="revenue" stroke="#66d9b8" strokeWidth={2} fill="url(#received)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
