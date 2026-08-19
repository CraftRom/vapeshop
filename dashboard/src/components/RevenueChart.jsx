import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

import { money } from './ui'

/**
 * Винесено в окремий чанк: recharts тягне d3 і важить більше за весь інший
 * код панелі разом узятий. Так метрики й таблиці показуються одразу, а графік
 * доїжджає слідом.
 */
export default function RevenueChart({ data }) {
  return (
    <div style={{ height: 260, marginTop: 14 }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
          <defs>
            <linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#8b7bf0" stopOpacity={0.45} />
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
              background: '#221e31',
              border: '1px solid #2e2840',
              borderRadius: 10,
              color: '#ece9f5',
            }}
            formatter={(value, name) =>
              name === 'revenue' ? [money(value), 'Виручка'] : [value, 'Замовлень']
            }
          />
          <Area type="monotone" dataKey="revenue" stroke="#8b7bf0" strokeWidth={2} fill="url(#rev)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
