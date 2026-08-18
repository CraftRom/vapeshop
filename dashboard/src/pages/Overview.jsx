import { useEffect, useState } from 'react'
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

import { api } from '../api'
import { STATUS_LABELS } from '../components/StatusRail'
import { ErrorBar, Loading, money } from '../components/ui'

const PERIODS = [
  { days: 7, label: '7 днів' },
  { days: 30, label: '30 днів' },
  { days: 90, label: '90 днів' },
]

function Metric({ label, value, sub, tone }) {
  return (
    <div className={`card metric ${tone || ''}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

export default function Overview() {
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError('')

    Promise.all([
      api.stats.summary(days),
      api.stats.series(Math.max(days, 7)),
      api.stats.topProducts(days),
      api.stats.breakdown(),
    ])
      .then(([summary, series, top, breakdown]) => {
        if (!cancelled) setData({ summary, series, top, breakdown })
      })
      .catch((err) => !cancelled && setError(err.message))

    return () => { cancelled = true }
  }, [days])

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Огляд</h1>
          <p>Як магазин працює за обраний період</p>
        </div>
        <div className="row">
          {PERIODS.map((p) => (
            <button
              key={p.days}
              className={`btn small ${days === p.days ? '' : 'ghost'}`}
              onClick={() => setDays(p.days)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <ErrorBar error={error} />

      {!data ? (
        <Loading rows={4} />
      ) : (
        <div className="stack">
          <div className="grid k4">
            <Metric
              label="Виручка за період"
              value={money(data.summary.revenue_period)}
              sub={`Усього: ${money(data.summary.revenue_total)}`}
              tone="accent"
            />
            <Metric
              label="Нові замовлення"
              value={data.summary.orders_new}
              sub={`Усього замовлень: ${data.summary.orders_total}`}
              tone={data.summary.orders_new > 0 ? 'warn' : ''}
            />
            <Metric
              label="Середній чек"
              value={money(data.summary.avg_check)}
              sub="За оплаченими замовленнями"
            />
            <Metric
              label="Клієнтів"
              value={data.summary.customers_total}
              sub={`+${data.summary.customers_period} за період`}
            />
          </div>

          {data.summary.low_stock > 0 && (
            <div className="card" style={{ borderColor: 'rgba(242,179,71,0.35)' }}>
              <div className="row">
                <span className="chip warn">Залишки</span>
                <span>
                  {data.summary.low_stock} товарів мають менше 5 шт на складі — перевірте каталог.
                </span>
              </div>
            </div>
          )}

          <div className="card">
            <h2>Виручка по днях</h2>
            <div style={{ height: 260, marginTop: 14 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.series} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
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
                  <Area
                    type="monotone"
                    dataKey="revenue"
                    stroke="#8b7bf0"
                    strokeWidth={2}
                    fill="url(#rev)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            {data.series.length === 0 && (
              <p className="muted" style={{ textAlign: 'center' }}>
                За цей період оплачених замовлень ще не було.
              </p>
            )}
          </div>

          <div className="grid k2">
            <div className="card">
              <h2>Топ товарів</h2>
              {data.top.length === 0 ? (
                <p className="muted">Продажів за період ще немає.</p>
              ) : (
                <div className="table-wrap" style={{ marginTop: 12 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Товар</th>
                        <th className="num">Шт</th>
                        <th className="num">Виручка</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.top.map((p) => (
                        <tr key={p.name}>
                          <td>{p.name}</td>
                          <td className="num">{p.qty}</td>
                          <td className="num">{money(p.revenue)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="card">
              <h2>Замовлення за статусами</h2>
              <div className="stack" style={{ marginTop: 14, gap: 10 }}>
                {data.breakdown.map((row) => (
                  <div className="row" key={row.status}>
                    <span style={{ flex: 1 }}>{STATUS_LABELS[row.status] || row.status}</span>
                    <span className="mono">{row.count}</span>
                  </div>
                ))}
                {data.breakdown.length === 0 && <p className="muted">Замовлень ще немає.</p>}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
