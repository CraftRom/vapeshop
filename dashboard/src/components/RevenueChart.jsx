import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

import { money } from './ui'

function normalizeSeries(data) {
  if (!Array.isArray(data)) return []
  return data.map((row) => ({
    ...row,
    // Decimal у FastAPI може серіалізуватися рядком. Recharts частково
    // приводив такі значення сам: координата малювалась, але domain Y
    // обчислювався некоректно. Через це великі суми обрізались верхом,
    // а monotone-інтерполяція перетворювала лінію на великі дуги.
    sales: Number(row?.sales ?? row?.confirmed ?? 0) || 0,
    revenue: Number(row?.revenue ?? 0) || 0,
    expected: Number(row?.expected ?? 0) || 0,
    orders: Number(row?.orders ?? 0) || 0,
    shipped: Number(row?.shipped ?? 0) || 0,
  }))
}

function compactMoney(value) {
  return Number(value || 0).toLocaleString('uk-UA', {
    maximumFractionDigits: 0,
    notation: Number(value || 0) >= 100000 ? 'compact' : 'standard',
  })
}

function displayDate(value) {
  if (!value || typeof value !== 'string') return value
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return value
  return new Intl.DateTimeFormat('uk-UA', { day: '2-digit', month: '2-digit' })
    .format(new Date(Date.UTC(year, month - 1, day)))
}

/**
 * Два фінансові шари на одному графіку:
 * sales — оборот лише замовлень із CRM-статусом «Продаж»; revenue — кошти,
 * які вже можна вважати отриманими. Логістичний статус відправлення сам по
 * собі не створює продаж і не малюється як гроші на рахунку.
 *
 * Лінія навмисно linear, а не monotone: календарні фінансові значення —
 * дискретні денні підсумки. Сплайн між нульовим днем і великим продажем
 * створював вигадані проміжні піки та дуги, яких у даних не існувало.
 */
export default function RevenueChart({ data }) {
  const chartData = normalizeSeries(data)

  return (
    <div className="stats-revenue-chart-shell">
      <div className="stats-chart-legend" aria-label="Легенда графіка">
        <span><i className="turnover" />Оборот продажів</span>
        <span><i className="received" />Отримано</span>
      </div>
      <div className="stats-revenue-chart">
        <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 10, right: 12, left: 4, bottom: 2 }}>
          <defs>
            <linearGradient id="received" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#66d9b8" stopOpacity={0.26} />
              <stop offset="100%" stopColor="#66d9b8" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="turnover" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#8b7bf0" stopOpacity={0.16} />
              <stop offset="100%" stopColor="#8b7bf0" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#2e2840" vertical={false} />
          <XAxis
            dataKey="date"
            stroke="#635b7d"
            fontSize={11}
            tickFormatter={displayDate}
            minTickGap={24}
            tickLine={false}
            axisLine={{ stroke: '#3a334d' }}
          />
          <YAxis
            stroke="#635b7d"
            fontSize={11}
            domain={[0, 'auto']}
            tickFormatter={compactMoney}
            tickLine={false}
            axisLine={false}
            width={58}
          />
          <Tooltip
            contentStyle={{
              background: '#221e31', border: '1px solid #2e2840', borderRadius: 10, color: '#ece9f5',
            }}
            labelFormatter={(value) => `Дата: ${displayDate(value)}`}
            formatter={(value, name) => {
              if (name === 'sales') return [money(value), 'Оборот продажів']
              if (name === 'revenue') return [money(value), 'Отримано']
              return [value, name]
            }}
          />
          <Area
            type="linear"
            dataKey="sales"
            stroke="#8b7bf0"
            strokeWidth={2}
            fill="url(#turnover)"
            baseValue={0}
            connectNulls={false}
            isAnimationActive={false}
            dot={false}
            activeDot={{ r: 4 }}
          />
          <Area
            type="linear"
            dataKey="revenue"
            stroke="#66d9b8"
            strokeWidth={2}
            fill="url(#received)"
            baseValue={0}
            connectNulls={false}
            isAnimationActive={false}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
