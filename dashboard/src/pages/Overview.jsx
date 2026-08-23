import { Suspense, lazy, useEffect, useState } from 'react'

import { api } from '../api'
import { STATUS_LABELS } from '../components/StatusRail'
import { ErrorBar, Loading, money } from '../components/ui'

const RevenueChart = lazy(() => import('../components/RevenueChart'))

/** Днів від початку поточного календарного місяця, включно з сьогодні.
 *
 * «Цей місяць» ≠ «30 днів»: власник звіряється з календарем, а не з
 * ковзним вікном, і 3 березня має бачити три дні, а не місяць.
 */
function daysThisMonth() {
  const now = new Date()
  return now.getDate()
}

const PERIODS = [
  { days: 1, label: 'Сьогодні' },
  { days: 7, label: '7 днів' },
  { days: daysThisMonth(), label: 'Цей місяць' },
  { days: 90, label: '90 днів' },
  { days: 0, label: 'Весь час' },
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
      // Графік завжди хоча б за тиждень: на одній точці він безглуздий
      api.stats.series(days === 0 ? 90 : Math.max(days, 7)),
      api.stats.topProducts(days),
      api.stats.breakdown(),
      api.stats.byOperator(days),
    ])
      .then(([summary, series, top, breakdown, operators]) => {
        if (!cancelled) setData({ summary, series, top, breakdown, operators })
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
              sub={`Оплачених за період: ${data.summary.orders_period}`}
              tone={data.summary.orders_new > 0 ? 'warn' : ''}
            />
            <Metric
              label="Середній чек за період"
              value={money(data.summary.avg_check_period)}
              sub={`За весь час: ${money(data.summary.avg_check)}`}
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
            <Suspense fallback={<div className="skeleton" style={{ height: 260, marginTop: 14 }} />}>
              <RevenueChart data={data.series} />
            </Suspense>

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

          <div className="card">
            <h2>Оператори за період</h2>
            {data.operators.length === 0 ? (
              <p className="muted">За цей період оплачених замовлень немає.</p>
            ) : (
              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table>
                  <thead>
                    <tr>
                      <th>Оператор</th>
                      <th className="num">Замовлень</th>
                      <th className="num">Виручка</th>
                      <th className="num">Середній чек</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.operators.map((o) => (
                      <tr key={o.operator_name}>
                        <td>{o.operator_name}</td>
                        <td className="num">{o.orders}</td>
                        <td className="num">{money(o.revenue)}</td>
                        <td className="num">{money(o.avg_check)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
