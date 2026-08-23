import { useEffect, useState } from 'react'

import { api, isAdmin } from '../api'
import { ErrorBar, Field, Loading, useToast } from '../components/ui'

// Оператор бачить лише реферальну програму: решта параметрів — реквізити,
// адреси, список менеджерів — за адміністратором. Бекенд це теж перевіряє,
// тут ми просто не показуємо те, що все одно не збережеться.
const ADMIN_ONLY = new Set(['Магазин', 'Оплата', 'Telegram-група', 'Бот і Mini App'])

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
    title: 'Telegram-група',
    hint: 'Куди бот надсилає нові замовлення і хто керує ними прямо в чаті.',
    items: [
      {
        key: 'admin_chat_id',
        label: 'ID чату для замовлень',
        hint: 'Наприклад -1001234567890. Додайте бота в групу як адміністратора, ' +
              'а щоб дізнатися ID — тимчасово додайте @getmyid_bot',
      },
      {
        key: 'admin_ids',
        label: 'Telegram ID менеджерів',
        hint: 'Через кому. Ці люди бачать /stats і кнопки статусу замовлень',
      },
    ],
  },
  {
    title: 'Бот і Mini App',
    hint: 'Адреси, з яких будуються кнопка магазину й реферальні посилання.',
    items: [
      {
        key: 'bot_username',
        label: 'Юзернейм бота',
        hint: 'Без «собаки», наприклад elfar1_bot',
      },
      {
        key: 'miniapp_short_name',
        label: 'Коротка назва Mini App',
        hint: 'Із BotFather → /newapp. Без неї реферальні посилання ' +
              'не відкриватимуть вітрину напряму',
      },
      {
        key: 'public_url',
        label: 'Адреса сайту',
        hint: 'Обовʼязково https:// і точно той домен, що віддає сайт — ' +
              'разом із www, якщо він є',
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

      {FIELDS.filter((g) => isAdmin() || !ADMIN_ONLY.has(g.title)).map((group) => (
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

      {!isAdmin() && (
        <div className="card" style={{ marginBottom: 18 }}>
          <p className="faint" style={{ margin: 0 }}>
            Решта налаштувань — реквізити оплати, адреси бота й вітрини, список
            менеджерів — доступна адміністратору.
          </p>
        </div>
      )}

      {isAdmin() && (
      <div className="card" style={{ marginBottom: 18 }}>
        <h2 style={{ marginTop: 0 }}>Що змінюється лише в оточенні</h2>
        <p className="faint" style={{ marginTop: -6 }}>
          Ці значення навмисно не редагуються тут: доступ до панелі не має
          означати повний контроль над ботом і базою.
        </p>
        <ul className="faint" style={{ margin: 0, paddingLeft: 18 }}>
          <li><code>BOT_TOKEN</code> — ключ бота</li>
          <li><code>JWT_SECRET</code>, <code>DASHBOARD_PASSWORD</code> — доступ до цієї панелі</li>
          <li><code>WEBHOOK_SECRET</code>, <code>CRON_SECRET</code> — службові секрети</li>
          <li><code>GOOGLE_APPLICATION_CREDENTIALS_JSON</code>, <code>REDIS_URL</code> — сховища</li>
        </ul>
      </div>
      )}

      <p className="faint">
        Порожнє поле повертає значення зі змінних оточення. Зміни доїжджають до бота
        протягом 30 секунд. Після зміни адреси сайту або назви Mini App напишіть боту
        <code> /start</code>, щоб кнопка перемалювалася з новим посиланням.
      </p>
    </>
  )
}
