import { useEffect, useState } from 'react'

import { api, isAdmin, isSysadmin } from '../api'
import { ErrorBar, Field, Loading, useToast } from '../components/ui'

// Менеджер бачить лише реферальну програму: решта параметрів — реквізити,
// адреси, список менеджерів — за адміністратором. Бекенд це теж перевіряє,
// тут ми просто не показуємо те, що все одно не збережеться.
// Доступно адміністраторові магазину.
const ADMIN_ONLY = new Set([
  'Магазин', 'Оплата', 'Доставка', 'Реквізити продавця',
])

// Доступно ЛИШЕ системному адміністраторові. Це не про довіру, а про ціну
// помилки: невірний токен бота чи зіпсований розклад бекапів кладе весь
// магазин, а не ділянку роботи однієї людини.
const SYSADMIN_ONLY = new Set([
  'Telegram-група', 'Бот і Mini App', 'Розсилки', 'Тихі години', 'Бекапи',
])

const FIELDS = [
  {
    title: 'Бонуси',
    toggle: 'bonus_enabled',
    hint: 'Вимкнений модуль клієнт не бачить зовсім: ні балансу, ні перемикача ' +
          'списання при оформленні. Нараховані бонуси зберігаються й повернуться, ' +
          'якщо ввімкнути знову.',
    items: [
      {
        key: 'bonus_max_percent',
        label: 'Ліміт оплати бонусами',
        type: 'number',
        hint: 'Максимальна частка замовлення, яку клієнт може закрити бонусами',
      },
    ],
  },
  {
    title: 'Реферальна програма',
    toggle: 'referral_enabled',
    hint: 'Потребує ввімкнених бонусів — винагорода нараховується саме ними. ' +
          'Вимкнена програма невидима: посилання й лічильник запрошених зникають.',
    items: [
      {
        key: 'referral_percent',
        label: 'Відсоток рефереру',
        type: 'number',
        hint: '% від суми виконаного замовлення запрошеного друга',
      },
    ],
  },
  {
    title: 'Знижка за суму',
    toggle: 'volume_discount_enabled',
    hint: 'Застосовується автоматично. З промокодом не додається — діє більша знижка, ' +
          'інакше великі чеки віддавалися б собі в збиток.',
    items: [
      {
        key: 'volume_discount_min',
        label: 'Від якої суми',
        type: 'number',
        hint: 'Знижка вмикається, коли сума товарів досягає цього значення',
      },
      {
        key: 'volume_discount_percent',
        label: 'Розмір знижки, %',
        type: 'number',
        hint: 'Скільки відсотків від суми товарів',
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
      {
        key: 'admin_topic_id',
        label: 'Гілка для замовлень',
        type: 'number',
        hint: 'Номер теми у форумі каналу. Відкрийте гілку у веб-версії — ' +
              'він стоїть після підкреслення в адресі, як-от .../#-1001234_792 → 792. ' +
              'Порожньо або 0 — писати в загальну стрічку',
      },
      {
        key: 'chat_topic_id',
        label: 'Гілка для повідомлень клієнтів',
        type: 'number',
        hint: 'Питання з чату замовлення. Окремо від самих замовлень: ' +
              'замовлення читають раз, а переписку ведуть далі, і в спільній ' +
              'стрічці нові замовлення тонули б у відповідях. 0 — разом із замовленнями',
      },
      {
        key: 'error_topic_id',
        label: 'Гілка для помилок',
        type: 'number',
        hint: 'Туди йдуть помилки сервера, бота й планувальника. Однакові ' +
              'згортаються, частота обмежена, тож стрічка не заллється',
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
        key: 'jwt_ttl_hours',
        label: 'Тривалість сесії в панелі, годин',
        type: 'number',
        hint: 'Через стільки годин доведеться увійти знову. Менше значення — ' +
              'безпечніше, якщо панеллю користуються зі спільного компʼютера',
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
    title: 'Реквізити продавця',
    hint: 'Підставляються в публічну оферту та політику обробки даних у вітрині. ' +
          'Поки поля порожні, документи показуються як незаповнена заготовка.',
    items: [
      { key: 'seller_name', label: 'Назва або ПІБ', hint: 'ФОП Галицький Дмитро / ТОВ «Назва»' },
      { key: 'seller_code', label: 'РНОКПП або ЄДРПОУ' },
      { key: 'seller_address', label: 'Адреса для листування' },
      { key: 'seller_email', label: 'Email для звернень', hint: 'Вказується як контакт у документах' },
      { key: 'seller_phone', label: 'Телефон' },
    ],
  },
  {
    title: 'Доставка',
    hint: 'Ключ до довідника Нової пошти дає вітрині показувати покупцеві ' +
          'список населених пунктів і відділень замість двох вільних рядків. ' +
          'Без ключа форма працює як раніше: адреса вписується руками.',
    items: [
      {
        key: 'novaposhta_api_key',
        label: 'Ключ API Нової пошти',
        secret: 'novaposhta_connected',
        hint: 'Кабінет Нової пошти → Налаштування → Безпека → Ключі API. ' +
              'Потрібен ключ з доступом до довідників',
      },
      {
        key: 'novaposhta_sender_city',
        label: 'Місто відправлення',
        hint: 'Назвою, як у довіднику: «Хмельницький». Потрібне для '
              + 'попереднього розрахунку доставки — без нього вітрина '
              + 'показує «від» із поля нижче',
      },
      {
        key: 'delivery_weight_per_item',
        label: 'Припущена вага позиції, кг',
        type: 'number',
        hint: 'Точної ваги товарів у каталозі немає, тож розрахунок і '
              + 'подається покупцеві як приблизний',
      },
      {
        key: 'delivery_cost_from',
        label: 'Доставка від, грн',
        type: 'number',
        hint: 'Запасний варіант: показується, коли розрахунок перевізника '
              + 'недоступний',
      },
      { key: 'delivery_days', label: 'Строк доставки', hint: 'Текстом: «1–3 дні»' },
      {
        key: 'cod_commission_percent',
        label: 'Комісія накладеного платежу, %',
        type: 'number',
      },
      {
        key: 'cod_commission_fixed',
        label: 'Фіксована комісія, грн',
        type: 'number',
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
  {
    title: 'Розсилки',
    hint: 'Планувальник перевіряє чергу раз на годину, тому відкладена розсилка ' +
          'стартує в межах години після заданого часу.',
    items: [
      {
        key: 'timezone',
        label: 'Часовий пояс магазину',
        hint: 'Назва IANA, наприклад Europe/Kyiv. За ним рахуються тихі години ' +
              'й час бекапу. Зсув на кшталт +02:00 не підійде: він ламається ' +
              'на переході на літній час',
      },
      {
        key: 'broadcast_rate_per_second',
        label: 'Повідомлень за секунду',
        type: 'number',
        hint: 'Telegram пропускає близько 30 на бота. Вище — починаються ' +
              'відмови з очікуванням, і розсилка йде повільніше, ніж на меншій швидкості',
      },
      {
        key: 'broadcast_chunk',
        label: 'Розмір порції',
        type: 'number',
        hint: 'Скільки отримувачів обробляється за один прохід. Курсор зберігається, ' +
              'тож розсилку можна зупинити й продовжити з того ж місця',
      },
    ],
  },
  {
    title: 'Тихі години',
    toggle: 'quiet_hours_enabled',
    hint: 'У цей проміжок розсилки не йдуть. Дозрілі не губляться — чекають ранку ' +
          'і стартують першим тіком після кінця тиші.',
    items: [
      { key: 'quiet_hours_start', label: 'Початок, година', type: 'number',
        hint: 'За часом магазину. Проміжок може перетинати північ: 22 → 9' },
      { key: 'quiet_hours_end', label: 'Кінець, година', type: 'number' },
    ],
  },
  {
    title: 'Бекапи',
    toggle: 'backup_enabled',
    hint: 'Планувальник знімає дамп через pg_dump раз на добу. Файли лягають ' +
          'у каталог backups поруч із docker-compose, звідки їх забирає restore.sh. ' +
          'Ротацію логів контейнерів тут не налаштувати: docker читає її при старті, ' +
          'тож вона лишається в docker-compose.prod.yml.',
    items: [
      { key: 'backup_hour', label: 'Година бекапу', type: 'number',
        hint: 'За часовим поясом магазину. Найкраще — коли замовлень найменше' },
      { key: 'backup_retention_days', label: 'Тримати дампи, днів', type: 'number',
        hint: 'Старші видаляються після кожного успішного бекапу' },
    ],
  },
]

const LEVEL = {
  critical: { label: 'критично', tone: 'bad' },
  important: { label: 'важливо', tone: 'warn' },
  optional: { label: 'необовʼязково', tone: '' },
}

/** Стан змінних оточення.
 *
 * Показує, що задано на сервері, і ніколи — самі значення. Без цього
 * екрана про незадану змінну дізнаються тоді, коли щось перестає
 * працювати, і причину шукають у логах.
 */
function EnvironmentCard() {
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.settings
      .environment()
      .then((data) => setItems(data.items))
      .catch((err) => setError(err.message))
  }, [])

  if (error) return <ErrorBar error={error} />
  if (!items) return null

  const problems = items.filter((i) => !i.ok && i.level !== 'optional')

  return (
    <div className="card" style={{ marginBottom: 18 }}>
      <div className="row-between">
        <h2 style={{ margin: 0 }}>Стан оточення</h2>
        <span className={`chip ${problems.length ? '' : 'ok'}`}>
          {problems.length ? `потребує уваги: ${problems.length}` : 'усе задано'}
        </span>
      </div>
      <p className="faint">
        Значення не показуються — лише те, задана змінна чи ні. Змінюються
        на сервері, у налаштуваннях розгортання.
      </p>

      <div className="table-wrap">
        <table>
          <tbody>
            {items.map((i) => (
              <tr key={i.key} style={{ opacity: i.ok ? 0.6 : 1 }}>
                <td style={{ width: 28 }}>{i.ok ? '✓' : '✗'}</td>
                <td><code>{i.key}</code></td>
                <td className="faint">{i.note}</td>
                <td>
                  {!i.ok && (
                    <span className="chip">{LEVEL[i.level]?.label || i.level}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

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

      {FIELDS.filter((g) => {
        if (SYSADMIN_ONLY.has(g.title)) return isSysadmin()
        if (ADMIN_ONLY.has(g.title)) return isAdmin()
        return true
      }).map((group) => (
        <div className="card" key={group.title} style={{ marginBottom: 18 }}>
          <div className="row-between">
            <h2 style={{ margin: 0 }}>{group.title}</h2>
            {group.toggle && (
              <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={Boolean(form[group.toggle])}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, [group.toggle]: e.target.checked }))
                  }
                />
                {form[group.toggle] ? 'Увімкнено' : 'Вимкнено'}
              </label>
            )}
          </div>
          {group.hint && <p className="faint">{group.hint}</p>}
          {/* Поля вимкненого модуля лишаються видимими, лише приглушеними:
              їх треба налаштувати ДО того, як вмикати */}
          <div style={{ opacity: group.toggle && !form[group.toggle] ? 0.45 : 1 }}>
          {group.items.map((item) => (
            <Field key={item.key} label={item.label} hint={item.hint}>
              <input
                className="input"
                type={item.secret ? 'password' : item.type || 'text'}
                value={form[item.key] ?? ''}
                onChange={set(item.key)}
                autoComplete={item.secret ? 'new-password' : undefined}
                placeholder={
                  item.secret
                    ? form[item.secret]
                      ? 'Збережений ключ. Впишіть новий, щоб замінити'
                      : 'Не заданий'
                    : undefined
                }
              />
              {/* Секрет не читається назад: ключем Нової пошти
                  створюються накладні від імені магазину, тож у
                  відповіді API йому не місце. Замість значення
                  показуємо стан — цього досить, щоб зрозуміти, чи
                  все налаштовано. */}
              {item.secret && (
                <p className="faint" style={{ margin: '6px 0 0' }}>
                  {form[item.secret]
                    ? 'Підключено. Прочитати збережений ключ назад не можна: '
                      + 'щоб замінити — впишіть новий, щоб відключити — очистіть '
                      + 'поле й збережіть.'
                    : 'Не підключено. Поки ключа немає, покупець вписує місто '
                      + 'й відділення руками.'}
                </p>
              )}
            </Field>
          ))}
          </div>
        </div>
      ))}

      {!isSysadmin() && (
        <div className="card" style={{ marginBottom: 18 }}>
          <p className="faint" style={{ margin: 0 }}>
            {isAdmin()
              ? 'Налаштування Telegram-групи, бота й Mini App, розсилок, тихих ' +
                'годин і бекапів змінює системний адміністратор — той, хто має ' +
                'доступ до сервера.'
              : 'Реквізити оплати, налаштування магазину й список облікових ' +
                'записів доступні адміністратору.'}
          </p>
        </div>
      )}

      {isSysadmin() && <EnvironmentCard />}

      {isSysadmin() && (
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
