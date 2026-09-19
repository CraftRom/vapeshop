import { Suspense, lazy, useEffect, useState } from 'react'

import { api } from '../api'
import { STATUS_LABELS } from '../components/StatusRail'
import { StatusBadge } from '../components/OrderStatus'
import { ErrorBar, Loading, money } from '../components/ui'

const RevenueChart = lazy(() => import('../components/RevenueChart'))

const PERIODS = [
  { key: 'today', label: 'Сьогодні' },
  { key: '7d', label: '7 днів' },
  { key: 'month', label: 'Цей місяць' },
  { key: '90d', label: '90 днів' },
  { key: 'all', label: 'Весь час' },
]

function Metric({ label, value, sub, tone, change }) {
  return (
    <div className={`card metric ${tone || ''}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {change !== undefined && change !== null && (
        <div className={`delta ${change >= 0 ? 'up' : 'down'}`}>
          {change >= 0 ? '▲' : '▼'} {Math.abs(change).toFixed(1)}% до попереднього періоду
        </div>
      )}
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']

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
              <div className="split-fill" style={{ width: `${(row.value / total) * 100}%` }} />
            </div>
            {row.note && <p className="faint" style={{ margin: '2px 0 0' }}>{row.note}</p>}
          </div>
        ))
      )}
    </div>
  )
}

function FinanceLegend({ summary }) {
  return (
    <div className="card stats-finance-legend">
      <div className="stats-finance-head">
        <div>
          <h2>Як рахуються гроші</h2>
          <p className="faint">Статистика не змішує підтверджений продаж із фактично отриманими коштами.</p>
        </div>
        <span className="chip">Період</span>
      </div>
      <div className="stats-finance-grid">
        <div>
          <span className="stats-finance-dot actual" />
          <div><b>Фактично в CRM</b><small>{money(summary.actual_received_period)}</small></div>
        </div>
        <div>
          <span className="stats-finance-dot calculated" />
          <div><b>Картка · за правилом</b><small>{money(summary.calculated_received_period)}</small></div>
        </div>
        <div>
          <span className="stats-finance-dot expected" />
          <div><b>Очікуємо</b><small>{money(summary.expected_period)}</small></div>
        </div>
      </div>
      <p className="faint stats-finance-note">
        Карткова оплата після етапу «Оплачено/Відправлено» вважається отриманою. Накладений платіж без фактичного платежу SalesDrive лишається очікуваним, навіть якщо посилка вже відправлена.
      </p>
    </div>
  )
}

function periodCaption(insights) {
  const start = insights?.period?.from
  const end = insights?.period?.to
  if (!start || !end) return ''
  const options = { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: insights.timezone || undefined }
  try {
    return `${new Date(start).toLocaleDateString('uk-UA', options)} — ${new Date(end).toLocaleDateString('uk-UA', options)}`
  } catch {
    return ''
  }
}

export default function Overview() {
  const [period, setPeriod] = useState('month')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError('')

    Promise.all([
      api.stats.summary(period),
      api.stats.series(period),
      api.stats.topProducts(period),
      api.stats.breakdown(period),
      api.stats.byOperator(period),
      api.stats.insights(period),
    ])
      .then(([summary, series, top, breakdown, operators, insights]) => {
        if (!cancelled) setData({ summary, series, top, breakdown, operators, insights })
      })
      .catch((err) => !cancelled && setError(err.message))

    return () => { cancelled = true }
  }, [period])

  const activity = data?.insights?.activity || {}
  const caption = period === 'all' ? 'за весь час' : periodCaption(data?.insights)

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Огляд</h1>
          <p>{caption ? (period === 'all' ? 'Статистика за весь час' : `Статистика за ${caption}`) : 'Фінанси, замовлення й активність магазину'}</p>
        </div>
        <div className="row stats-periods">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              className={`btn small ${period === p.key ? '' : 'ghost'}`}
              onClick={() => setPeriod(p.key)}
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
          <div className="grid k4 stats-primary-metrics">
            <Metric
              label="Отримано"
              value={money(data.summary.revenue_period)}
              change={data.insights?.revenue?.change}
              sub={`Факт CRM ${money(data.summary.actual_received_period)} · картка за правилом ${money(data.summary.calculated_received_period)}`}
              tone="accent"
            />
            <Metric
              label="Підтверджений оборот"
              value={money(data.summary.confirmed_period)}
              change={data.insights?.turnover?.change}
              sub={`${data.summary.confirmed_orders_period} підтверджених замовлень`}
            />
            <Metric
              label="Очікуємо отримання"
              value={money(data.summary.expected_period)}
              sub="Підтверджено, але гроші ще не вважаються отриманими"
              tone={Number(data.summary.expected_period) > 0 ? 'warn' : ''}
            />
            <Metric
              label="Відправлено"
              value={money(data.summary.shipped_period)}
              sub={`${data.summary.shipped_orders_period} замовлень уже дійшли до етапу відправки`}
            />
            <Metric
              label="Середній чек"
              value={money(data.summary.avg_check_period)}
              change={data.insights?.avg_check?.change}
              sub={`За весь час: ${money(data.summary.avg_check)}`}
            />
            <Metric
              label="Активні користувачі"
              value={data.summary.active_users_period}
              sub={`${data.summary.active_users_24h} були активні за останні 24 години`}
            />
            <Metric
              label="Нові користувачі"
              value={data.summary.customers_period}
              sub={`Усього клієнтів: ${data.summary.customers_total}`}
            />
            <Metric
              label="Покупці за період"
              value={data.summary.buyers_period}
              sub={`${activity.buyer_share ?? 0}% від активних користувачів оформили підтверджене замовлення`}
            />
            <Metric
              label="Нові замовлення зараз"
              value={data.summary.orders_new}
              sub={`Усього замовлень у базі: ${data.summary.orders_total}`}
              tone={data.summary.orders_new > 0 ? 'warn' : ''}
            />
          </div>

          <FinanceLegend summary={data.summary} />

          <div className="grid k2">
            <Metric
              label="Повторні покупки"
              value={`${data.insights?.repeat?.share ?? 0}%`}
              sub={`${data.insights?.repeat?.returning_orders ?? 0} повторних · ${data.insights?.repeat?.new_orders ?? 0} перших покупок`}
              tone={(data.insights?.repeat?.share ?? 0) >= 30 ? 'accent' : ''}
            />
            <Metric
              label="Скасовано"
              value={`${data.insights?.cancelled?.orders ?? 0}`}
              sub={`${data.insights?.cancelled?.share ?? 0}% створених · втрачений потенційний оборот ${money(data.insights?.cancelled?.lost ?? 0)}`}
              tone={(data.insights?.cancelled?.share ?? 0) >= 15 ? 'warn' : ''}
            />
          </div>

          {data.summary.low_stock > 0 && (
            <div className="card" style={{ borderColor: 'rgba(242,179,71,0.35)' }}>
              <div className="row">
                <span className="chip warn">Залишки</span>
                <span>{data.summary.low_stock} товарів мають менше 5 шт на складі — перевірте каталог.</span>
              </div>
            </div>
          )}

          <div className="card">
            <div className="stats-section-title">
              <div>
                <h2>Оборот і отримані кошти по днях</h2>
                <p className="faint">Підтверджений оборот показує продажі, «отримано» — лише гроші, які вже можна зарахувати за правилами оплати.</p>
              </div>
            </div>
            <Suspense fallback={<div className="skeleton" style={{ height: 260, marginTop: 14 }} />}>
              <RevenueChart data={data.series} />
            </Suspense>
            {data.series.length === 0 && (
              <p className="muted" style={{ textAlign: 'center' }}>За цей період підтверджених замовлень ще не було.</p>
            )}
          </div>

          <div className="grid k2">
            <div className="card">
              <h2>Топ товарів</h2>
              <p className="faint">За підтвердженими замовленнями вибраного періоду.</p>
              {data.top.length === 0 ? (
                <p className="muted">Підтверджених продажів за період ще немає.</p>
              ) : (
                <div className="table-wrap" style={{ marginTop: 12 }}>
                  <table>
                    <thead><tr><th>Товар</th><th className="num">Шт</th><th className="num">Оборот</th></tr></thead>
                    <tbody>
                      {data.top.map((p) => (
                        <tr key={p.name}><td>{p.name}</td><td className="num">{p.qty}</td><td className="num">{money(p.revenue)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="card">
              <h2>Замовлення за статусами</h2>
              <p className="faint">Тільки замовлення вибраного періоду; CRM і legacy не змішуються.</p>
              <div className="stack" style={{ marginTop: 14, gap: 10 }}>
                {data.breakdown.map((row) => (
                  <div className="row status-breakdown-row" key={`${row.source || 'legacy'}:${row.status}`}>
                    <span style={{ flex: 1 }}>
                      <StatusBadge
                        source={row.source || 'legacy'}
                        id={row.status}
                        name={row.source === 'crm' ? (row.name || `Статус CRM #${row.status}`) : (STATUS_LABELS[row.status] || row.status)}
                        compact
                      />
                    </span>
                    <span className="mono">{row.count}</span>
                  </div>
                ))}
                {data.breakdown.length === 0 && <p className="muted">Замовлень за період немає.</p>}
              </div>
            </div>
          </div>

          <div className="grid k2">
            <Split
              title="Як платять"
              hint="Оборот і отримані кошти показуються окремо: накладений платіж до фактичної оплати лишається очікуваним."
              rows={[
                {
                  label: 'Переказ на картку',
                  value: data.insights.payment.card.orders,
                  note: `оборот ${money(data.insights.payment.card.revenue)} · отримано ${money(data.insights.payment.card.received)} · очікуємо ${money(data.insights.payment.card.expected)}`,
                },
                {
                  label: 'Накладений платіж',
                  value: data.insights.payment.cod.orders,
                  note: `оборот ${money(data.insights.payment.cod.revenue)} · отримано ${money(data.insights.payment.cod.received)} · очікуємо ${money(data.insights.payment.cod.expected)}`,
                },
              ]}
            />
            <Split
              title="Куди возимо"
              hint="Розподіл лише підтверджених замовлень за вибраний період."
              rows={[
                { label: 'Відділення', value: data.insights.delivery.warehouse },
                { label: 'Курʼєр на адресу', value: data.insights.delivery.courier },
                { label: 'Не вказано', value: data.insights.delivery.unknown },
              ]}
            />
          </div>

          <div className="card stats-activity-card">
            <div className="stats-section-title">
              <div>
                <h2>Активність користувачів</h2>
                <p className="faint">Активність визначається за last_seen у вітрині/боті, покупки — за підтвердженими замовленнями.</p>
              </div>
              <span className="chip">{data.insights.timezone || 'Europe/Kyiv'}</span>
            </div>
            <div className="stats-activity-grid">
              <div><span>Активні за період</span><strong>{activity.active_users ?? 0}</strong></div>
              <div><span>Активні 24 год</span><strong>{activity.active_24h ?? 0}</strong></div>
              <div><span>Нові користувачі</span><strong>{activity.new_users ?? 0}</strong></div>
              <div><span>Покупці</span><strong>{activity.buyers ?? 0}</strong></div>
              <div><span>Конверсія активних</span><strong>{activity.buyer_share ?? 0}%</strong></div>
            </div>
          </div>

          <Bars
            title="Коли замовляють: години доби"
            hint={`Підтверджені замовлення за локальним часом магазину (${data.insights.timezone || 'Europe/Kyiv'}).`}
            labels={Array.from({ length: 24 }, (_, h) => String(h))}
            values={data.insights.by_hour}
          />

          <Bars
            title="Коли замовляють: дні тижня"
            hint="Період визначається календарними межами: «Сьогодні» — від 00:00, «Цей місяць» — від першого числа."
            labels={WEEKDAYS}
            values={data.insights.by_weekday}
          />

          <div className="card">
            <h2>Менеджери за період</h2>
            <p className="faint">Оборот — усі підтверджені замовлення; отримано й очікуємо показані окремо.</p>
            {data.operators.length === 0 ? (
              <p className="muted">За цей період підтверджених замовлень немає.</p>
            ) : (
              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table>
                  <thead>
                    <tr>
                      <th>Менеджер</th>
                      <th className="num">Замовлень</th>
                      <th className="num">Оборот</th>
                      <th className="num">Отримано</th>
                      <th className="num">Очікуємо</th>
                      <th className="num">Сер. чек</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.operators.map((o) => (
                      <tr key={o.operator_name}>
                        <td>{o.operator_name}</td>
                        <td className="num">{o.orders}</td>
                        <td className="num">{money(o.revenue)}</td>
                        <td className="num">{money(o.received)}</td>
                        <td className="num">{money(o.expected)}</td>
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
