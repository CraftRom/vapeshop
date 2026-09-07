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

function Metric({ label, value, sub, tone, change }) {
  return (
    <div className={`card metric ${tone || ''}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {/* Зміна до попереднього такого самого періоду. Без неї число
          відповідає «скільки», але не «краще чи гірше», а рішення
          ухвалюють саме з другого. */}
      {change !== undefined && change !== null && (
        <div className={`delta ${change >= 0 ? 'up' : 'down'}`}>
          {change >= 0 ? '▲' : '▼'} {Math.abs(change).toFixed(1)}% до минулого періоду
        </div>
      )}
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']

/** Стовпчики без бібліотеки: сім або двадцять чотири значення не варті
 *  ще одного графіка на 390 kB, а прочитати їх треба з одного погляду. */
function Bars({ title, hint, labels, values }) {
  const peak = Math.max(1, ...values)
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{title}</h2>
      {hint && <p className="faint" style={{ marginTop: 0 }}>{hint}</p>}
      <div className="bars">
        {values.map((value, index) => (
          <div className="bar-slot" key={labels[index]}>
            <div className="bar-track">
              <div
                className={`bar-fill ${value === peak && value > 0 ? 'peak' : ''}`}
                style={{ height: `${Math.round((value / peak) * 100)}%` }}
                title={`${labels[index]}: ${value}`}
              />
            </div>
            <span className="bar-label">{labels[index]}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Split({ title, hint, rows }) {
  const total = rows.reduce((sum, row) => sum + row.value, 0)
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{title}</h2>
      {hint && <p className="faint" style={{ marginTop: 0 }}>{hint}</p>}
      {total === 0 ? (
        <p className="faint">За цей період даних немає.</p>
      ) : (
        rows.map((row) => (
          <div className="split-row" key={row.label}>
            <div className="row-between">
              <span>{row.label}</span>
              <span className="num">
                {row.value} · {Math.round((row.value / total) * 100)}%
              </span>
            </div>
            <div className="split-track">
              <div
                className="split-fill"
                style={{ width: `${(row.value / total) * 100}%` }}
              />
            </div>
            {row.note && <p className="faint" style={{ margin: '2px 0 0' }}>{row.note}</p>}
          </div>
        ))
      )}
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
      // «Весь час» порівнювати нема з чим — попереднього періоду не
      // існує. Тоді беремо рік: розрізи лишаються, порівняння зникає.
      api.stats.insights(days === 0 ? 365 : Math.max(days, 1)),
    ])
      .then(([summary, series, top, breakdown, operators, insights]) => {
        if (!cancelled) setData({ summary, series, top, breakdown, operators, insights })
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
              change={data.insights?.revenue?.change}
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
              change={data.insights?.avg_check?.change}
              sub={`За весь час: ${money(data.summary.avg_check)}`}
            />
            <Metric
              label="Клієнтів"
              value={data.summary.customers_total}
              sub={`+${data.summary.customers_period} за період`}
            />
            <Metric
              label="Повторні покупки"
              value={`${data.insights?.repeat?.share ?? 0}%`}
              sub={
                `${data.insights?.repeat?.returning_orders ?? 0} повернулись, `
                + `${data.insights?.repeat?.new_orders ?? 0} вперше`
              }
              tone={(data.insights?.repeat?.share ?? 0) >= 30 ? 'accent' : ''}
            />
            <Metric
              label="Скасовано"
              value={`${data.insights?.cancelled?.orders ?? 0}`}
              sub={
                `${data.insights?.cancelled?.share ?? 0}% замовлень періоду · `
                + `не отримано ${money(data.insights?.cancelled?.lost ?? 0)}`
              }
              tone={(data.insights?.cancelled?.share ?? 0) >= 15 ? 'warn' : ''}
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

          {data.insights && (
            <>
              <div className="grid k2">
                <Split
                  title="Як платять"
                  hint="Накладений платіж дорожчий для нас і частіше повертається, але без нього частина покупців не замовляє взагалі."
                  rows={[
                    {
                      label: 'Переказ на картку',
                      value: data.insights.payment.card.orders,
                      note: money(data.insights.payment.card.revenue),
                    },
                    {
                      label: 'Накладений платіж',
                      value: data.insights.payment.cod.orders,
                      note: money(data.insights.payment.cod.revenue),
                    },
                  ]}
                />
                <Split
                  title="Куди возимо"
                  hint="Якщо курʼєром замовляють одиниці, його можна вимкнути; якщо навпаки — варто розширювати."
                  rows={[
                    { label: 'Відділення', value: data.insights.delivery.warehouse },
                    { label: 'Курʼєр на адресу', value: data.insights.delivery.courier },
                    { label: 'Не вказано', value: data.insights.delivery.unknown },
                  ]}
                />
              </div>

              <Bars
                title="Коли замовляють: години доби"
                hint="За цим ставлять час відправок і зміни менеджерів: пік — це коли на повідомлення чекають відповіді одразу."
                labels={Array.from({ length: 24 }, (_, h) => String(h))}
                values={data.insights.by_hour}
              />

              <Bars
                title="Коли замовляють: дні тижня"
                hint="Провал у певний день — привід перевірити, чи працює доставка саме тоді, а не вважати його мертвим."
                labels={WEEKDAYS}
                values={data.insights.by_weekday}
              />
            </>
          )}

          <div className="card">
            <h2>Менеджери за період</h2>
            {data.operators.length === 0 ? (
              <p className="muted">За цей період оплачених замовлень немає.</p>
            ) : (
              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table>
                  <thead>
                    <tr>
                      <th>Менеджер</th>
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
