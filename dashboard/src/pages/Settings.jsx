import { useEffect, useState } from 'react'

import { api } from '../api'
import { ErrorBar, Field, Loading, useToast } from '../components/ui'

const FIELDS = [
  {
    title: 'Реферальна програма',
    hint: 'Змінюється на льоту — редеплой не потрібен. Уже нараховані бонуси не перераховуються.',
    items: [
      {
        key: 'referral_percent',
        label: 'Відсоток рефереру',
        type: 'number',
        hint: '% від суми виконаного замовлення запрошеного друга, нараховується бонусами',
      },
      {
        key: 'bonus_max_percent',
        label: 'Ліміт оплати бонусами',
        type: 'number',
        hint: 'Максимальна частка замовлення, яку клієнт може закрити бонусами',
      },
    ],
  },
  {
    title: 'Магазин',
    items: [
      { key: 'shop_name', label: 'Назва магазину', hint: 'Показується у вітанні бота' },
      { key: 'currency', label: 'Валюта', hint: 'Підпис до сум: грн, ₴, UAH' },
      {
        key: 'min_age',
        label: 'Мінімальний вік',
        type: 'number',
        hint: 'Вік у тексті підтвердження. Не менше 18',
      },
    ],
  },
  {
    title: 'Оплата',
    hint: 'Ці реквізити бот надсилає клієнту після оформлення замовлення з оплатою карткою.',
    items: [
      { key: 'card_number', label: 'Номер картки' },
      { key: 'card_holder', label: 'Власник картки' },
    ],
  },
]

export default function Settings() {
  const notify = useToast()
  const [form, setForm] = useState(null)
  const [initial, setInitial] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.settings
      .get()
      .then((data) => {
        setForm(data)
        setInitial(data)
      })
      .catch((err) => setError(err.message))
  }, [])

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const dirty =
    form && initial && Object.keys(form).some((k) => String(form[k]) !== String(initial[k]))

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const saved = await api.settings.update(form)
      setForm(saved)
      setInitial(saved)
      notify('Налаштування збережено')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const reset = () => setForm(initial)

  if (error && !form) return <ErrorBar error={error} />
  if (!form) return <Loading />

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Налаштування</h1>
          <p>Параметри магазину, які раніше задавалися лише змінними оточення</p>
        </div>
        <div className="row">
          <button className="btn ghost" onClick={reset} disabled={!dirty || busy}>
            Скасувати
          </button>
          <button className="btn" onClick={save} disabled={!dirty || busy}>
            {busy ? 'Збереження…' : 'Зберегти'}
          </button>
        </div>
      </div>

      <ErrorBar error={error} />

      {FIELDS.map((group) => (
        <div className="card" key={group.title} style={{ marginBottom: 18 }}>
          <h2 style={{ marginTop: 0 }}>{group.title}</h2>
          {group.hint && <p className="faint" style={{ marginTop: -6 }}>{group.hint}</p>}
          {group.items.map((item) => (
            <Field key={item.key} label={item.label} hint={item.hint}>
              <input
                className="input"
                type={item.type || 'text'}
                value={form[item.key] ?? ''}
                onChange={set(item.key)}
              />
            </Field>
          ))}
        </div>
      ))}

      <p className="faint">
        Порожнє поле повертає значення зі змінних оточення. Зміни доїжджають до бота
        протягом 30 секунд.
      </p>
    </>
  )
}
