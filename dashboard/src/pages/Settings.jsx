import { useEffect, useState } from 'react'

import { api, isAdmin, isSysadmin } from '../api'
import { ErrorBar, Field, Loading, useToast } from '../components/ui'

// Менеджер бачить лише реферальну програму: решта параметрів — реквізити,
// адреси, список менеджерів — за адміністратором. Бекенд це теж перевіряє,
// тут ми просто не показуємо те, що все одно не збережеться.
// Доступно адміністраторові магазину.
const ADMIN_ONLY = new Set([
  'Магазин', 'Доставка', 'Реквізити продавця',
])

// Доступно ЛИШЕ системному адміністраторові. Це не про довіру, а про ціну
// помилки: невірний токен бота чи зіпсований розклад бекапів кладе весь
// магазин, а не ділянку роботи однієї людини.
const SYSADMIN_ONLY = new Set([
  'Telegram-група', 'Бот і Mini App', 'Розсилки', 'Тихі години', 'Бекапи',
  'SalesDrive',
])

// Статуси й способи — ключі відповідностей SalesDrive. Порядок і назви ті
// самі, що бачить менеджер у замовленні.
const STATUS_KEYS = [
  ['new', 'Нове'], ['confirmed', 'Підтверджене'], ['accepted', 'Прийняте в роботу'],
  ['paid', 'Оплачене'], ['shipped', 'Відправлене'], ['done', 'Виконане'],
  ['cancelled', 'Скасоване'],
]
const PAYMENT_KEYS = [['card', 'Переказ на картку'], ['cod', 'Накладений платіж']]
const SHIPPING_KEYS = [['warehouse', 'Відділення Нової пошти'], ['courier', 'Курʼєр на адресу']]

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
        key: 'faq_public_enabled',
        label: 'Відповіді на ключові слова у звичайних групах',
        bool: true,
        hint: 'Клієнтські чати. Увімкнено — бот сам відповідає, коли впізнає '
              + 'питання про доставку, оплату чи повернення: людина отримує '
              + 'відповідь уночі й не чекає менеджера',
      },
      {
        key: 'faq_admin_chat_enabled',
        label: 'Те саме в робочому чаті замовлень',
        bool: true,
        hint: 'Окремо, бо чат інший за призначенням: там працює команда, і '
              + 'довідка для клієнтів посеред її розмови — шум. Вимкнено за '
              + 'замовчуванням. Пряме звернення через @ працює за будь-якого '
              + 'положення обох перемикачів',
      },
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
        secretHint: 'Поки ключа немає, покупець вписує місто й відділення руками, '
          + 'а ТТН з панелі не створюється.',
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
        key: 'delivery_courier_enabled',
        label: 'Курʼєр на адресу',
        bool: true,
        hint: 'Вимкнено — покупець бачить лише відділення, і вибору способу '
              + 'доставки у формі немає зовсім. Показана, але недоступна '
              + 'насправді опція коштує скасованого замовлення',
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
        key: 'novaposhta_sender_phone',
        label: 'Телефон відправника для ТТН',
        hint: 'Той, що вказаний у кабінеті Нової пошти. Контрагента й контактну '
          + 'особу панель знаходить сама за ключем',
      },
      {
        key: 'novaposhta_sender_warehouse_ref',
        label: 'Код відділення відправлення',
        hint: 'Ref відділення, з якого відправляєте (довідник Нової пошти, '
          + 'getWarehouses). Без нього ТТН з панелі не створюється',
      },
      {
        key: 'novaposhta_sender_warehouse',
        label: 'Відділення відправлення (назва)',
        hint: 'Для людей: щоб через рік було зрозуміло, що це за код',
      },
      {
        key: 'novaposhta_cargo_description',
        label: 'Опис вантажу в ТТН',
        hint: 'Одним словом, як вимагає перевізник: «Товари»',
      },
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
    title: 'SalesDrive',
    toggle: 'salesdrive_enabled',
    hint: 'Замовлення магазину створюються в SalesDrive заявками, статуси й ТТН ' +
          'синхронізуються в обидва боки. Правила переходів ті самі, що й у панелі: ' +
          'статус із CRM, який магазин не дозволяє, не застосується — причина буде ' +
          'видна біля замовлення. Заявки, створені в CRM руками, у магазин не переносяться.',
    items: [
      { key: 'salesdrive_domain', label: 'Субдомен', hint: 'Лише субдомен: «elfar» для elfar.salesdrive.me' },
      { key: 'salesdrive_telegram_form_id', label: 'ID форми Telegram', type: 'number',
        hint: 'formId окремої бази заявок «ELFAR — Telegram Bot». Інтеграція приймає webhook лише з цієї бази.' },
      {
        key: 'salesdrive_form_key',
        label: 'Ключ форми (бази заявок)',
        secret: 'salesdrive_form_connected',
        secretHint: 'Без ключа форми заявки не створюються й не оновлюються.',
        hint: 'Установки → Загальні налаштування і інтеграції → Інтеграція з сайтом',
      },
      {
        key: 'salesdrive_api_key',
        label: 'API-ключ',
        secret: 'salesdrive_api_connected',
        secretHint: 'Потрібен для перевірки звʼязку. Установки → Інші сервіси → API → API-ключі.',
      },
      { key: 'salesdrive_webhook_token', label: 'Адреса вебхука', webhook: 'salesdrive_webhook_connected' },
      { key: 'salesdrive_site', label: 'Сайт у заявці', hint: 'Поле «Сайт». Порожнє — домен магазину' },
      { key: 'salesdrive_status_map', label: 'Статуси', map: STATUS_KEYS,
        hint: 'statusId із SalesDrive для кожного статусу магазину. Кілька статусів можна вести в один' },
      { key: 'salesdrive_payment_map', label: 'Способи оплати', map: PAYMENT_KEYS,
        hint: 'Назва способу оплати так, як вона записана в SalesDrive' },
      { key: 'salesdrive_shipping_map', label: 'Способи доставки', map: SHIPPING_KEYS,
        hint: 'Назва способу доставки так, як вона записана в SalesDrive' },
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

// Що панель має право надсилати назад.
//
// Відповідь із налаштуваннями містить не лише поля форми: у ній є ще й
// похідні ознаки на кшталт novaposhta_connected — стан замість секрету,
// який назад не читається. Відправити таку ознаку на запис не можна,
// бо на боці API дозволені поля перелічені поіменно, і зайве ім'я
// відхиляється разом з усім запитом. Тому шлемо рівно те, що є у формі,
// а не все, що прийшло.
/** Розділи, доступні поточній ролі.
 *
 * Одне джерело і для показу, і для запису. Раніше показ фільтрувався за
 * роллю, а на збереження йшли ВСІ поля — включно з розділами, яких роль
 * навіть не бачить. Бекенд перевіряє права поіменно й відхиляє весь
 * запит цілком, тож менеджер не міг зберегти нічого взагалі, а
 * адміністратор спотикався об інфраструктурні поля. Ззовні це виглядало
 * як «налаштування не працюють».
 */
function visibleGroups() {
  return FIELDS.filter((group) => {
    if (SYSADMIN_ONLY.has(group.title)) return isSysadmin()
    if (ADMIN_ONLY.has(group.title)) return isAdmin()
    return true
  })
}

/** Що саме ця роль має право надсилати.
 *
 * Разом із перемикачем розділу: він живе поруч із заголовком, а не серед
 * полів, і його легко загубити. Саме так і сталось — перемикач «Бонуси»
 * переставав зберігатися.
 */
function editableKeys() {
  return new Set(visibleGroups().flatMap(
    (group) => [...group.items.map((i) => i.key), group.toggle].filter(Boolean),
  ))
}

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

/** Відповідність «статус магазину → значення SalesDrive» рядками.
 *
 * Зберігається JSON-ом, але редагувати JSON руками — вірний спосіб
 * пропустити кому й вимкнути синхронізацію статусів. Порожні рядки у
 * відповідність не потрапляють: такий статус просто не передається.
 */
function MapEditor({ keys, value, onChange, options = [] }) {
  let data = {}
  try { data = JSON.parse(value || '{}') || {} } catch { data = {} }
  const update = (key, next) => {
    const merged = { ...data, [key]: next }
    Object.keys(merged).forEach((k) => { if (!String(merged[k] ?? '').trim()) delete merged[k] })
    onChange(Object.keys(merged).length ? JSON.stringify(merged) : '')
  }
  return (
    <div className="map-editor">
      {keys.map(([key, label]) => (
        <div className="map-row" key={key}>
          <span>{label}</span>
          <select className="input" value={data[key] ?? ''} onChange={(e) => update(key, e.target.value)}>
            <option value="">не передавати</option>
            {options.map((option) => (
              <option key={option.id} value={option.id}>{option.name} · {option.id}</option>
            ))}
          </select>
        </div>
      ))}
    </div>
  )
}

/** Токен вебхука: генерується в браузері й показується один раз.
 *
 * Як і ключі, назад він не читається — адреса з токеном дає змінювати
 * статуси й ТТН замовлень. Тому адресу видно лише одразу після генерації,
 * до збереження: скопіювати в SalesDrive, зберегти, і далі — лише стан.
 */
function WebhookToken({ connected, value, onChange }) {
  const generate = () => {
    const bytes = new Uint8Array(32)
    crypto.getRandomValues(bytes)
    const token = btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    onChange(token)
  }
  const url = value ? `${window.location.origin}/api/integrations/salesdrive/webhook/${value}` : ''
  return (
    <div>
      <button type="button" className="btn ghost small" onClick={generate}>
        {connected ? 'Згенерувати нову адресу' : 'Згенерувати адресу'}
      </button>
      {url ? (
        <p className="faint webhook-url" style={{ margin: '8px 0 0' }}>
          Скопіюйте в SalesDrive (Установки → Інші сервіси → Webhook, події «Нова заявка» й
          «Зміна статусу», повна інформація), потім збережіть налаштування:
          <br /><code>{url}</code>
        </p>
      ) : (
        <p className="faint" style={{ margin: '6px 0 0' }}>
          {connected
            ? 'Адресу задано. Прочитати її назад не можна; нова адреса робить стару недійсною.'
            : 'Не задано — зміни з SalesDrive у магазин не надходять.'}
        </p>
      )}
    </div>
  )
}

function SalesDriveCheck() {
  const [state, setState] = useState(null)
  const [busy, setBusy] = useState(false)
  const check = async () => {
    setBusy(true)
    try {
      setState(await api.settings.salesdriveCheck())
    } catch (err) {
      setState({ ok: false, problem: err.message })
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="row" style={{ marginTop: 8 }}>
      <button type="button" className="btn ghost small" onClick={check} disabled={busy}>
        {busy ? 'Перевірка…' : 'Перевірити звʼязок'}
      </button>
      {state && (
        <span className={`chip ${state.ok ? 'ok' : 'bad'}`}>
          {state.ok ? 'SalesDrive відповідає' : state.problem}
        </span>
      )}
      <span className="faint">Перевіряє субдомен і API-ключ збереженими значеннями</span>
    </div>
  )
}

export default function Settings() {
  const notify = useToast()
  const [form, setForm] = useState(null)
  const [initial, setInitial] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [sdDicts, setSdDicts] = useState({ statuses: [], payments: [], deliveries: [] })
  const [sdDictError, setSdDictError] = useState('')
  const [sdDictBusy, setSdDictBusy] = useState(false)

  const loadSalesDriveDictionaries = async () => {
    setSdDictBusy(true)
    setSdDictError('')
    try {
      setSdDicts(await api.settings.salesdriveDictionaries())
    } catch (err) {
      setSdDictError(err.message)
    } finally {
      setSdDictBusy(false)
    }
  }

  useEffect(() => {
    api.settings
      .get()
      .then((data) => {
        setForm(data)
        setInitial(data)
      })
      .catch((err) => setError(err.message))
  }, [])

  useEffect(() => { loadSalesDriveDictionaries() }, [])

  const autoMapSalesDrive = () => {
    const norm = (v) => String(v || '').toLowerCase().replace(/[ʼ'’]/g, '').replace(/[^a-zа-яіїєґ0-9]+/giu, ' ').trim()
    const find = (items, words) => items.find((item) => words.some((word) => norm(item.name).includes(norm(word))))
    const statusAliases = {
      new: ['нов', 'new'], confirmed: ['підтвердж', 'подтверж', 'confirm'],
      accepted: ['прийнят', 'в робот', 'в роботу', 'processing'], paid: ['оплачен', 'paid'],
      shipped: ['відправ', 'отправ', 'shipped'], done: ['виконан', 'заверш', 'успіш', 'done'],
      cancelled: ['скасован', 'отмен', 'cancel'],
    }
    const paymentAliases = { card: ['карт', 'переказ', 'безготів', 'iban'], cod: ['наклад', 'післяплат', 'налож'] }
    const shippingAliases = { warehouse: ['нова пошт', 'відділен', 'warehouse'], courier: ['курєр', 'курьер', 'адрес', 'courier'] }
    const build = (aliases, items) => Object.fromEntries(Object.entries(aliases).flatMap(([key, words]) => {
      const hit = find(items, words); return hit ? [[key, hit.id]] : []
    }))
    const statusMap = build(statusAliases, sdDicts.statuses)
    const paymentMap = build(paymentAliases, sdDicts.payments)
    const shippingMap = build(shippingAliases, sdDicts.deliveries)
    setForm((f) => ({ ...f,
      salesdrive_status_map: Object.keys(statusMap).length ? JSON.stringify(statusMap) : f.salesdrive_status_map,
      salesdrive_payment_map: Object.keys(paymentMap).length ? JSON.stringify(paymentMap) : f.salesdrive_payment_map,
      salesdrive_shipping_map: Object.keys(shippingMap).length ? JSON.stringify(shippingMap) : f.salesdrive_shipping_map,
    }))
    notify('Автозіставлення застосовано. Перевірте вибрані значення перед збереженням.')
  }

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const dirty = Boolean(form && initial) && [...editableKeys()].some(
    (key) => String(form[key]) !== String(initial[key]),
  )

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      const mine = editableKeys()
      const payload = Object.fromEntries(
        Object.entries(form).filter(([key]) => mine.has(key)),
      )
      const saved = await api.settings.update(payload)
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

      {visibleGroups().map((group) => (
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
              {item.map ? (
                <MapEditor
                  keys={item.map}
                  value={form[item.key]}
                  options={item.key === 'salesdrive_status_map' ? sdDicts.statuses : item.key === 'salesdrive_payment_map' ? sdDicts.payments : sdDicts.deliveries}
                  onChange={(value) => setForm((f) => ({ ...f, [item.key]: value }))}
                />
              ) : item.webhook ? (
                <WebhookToken
                  connected={Boolean(form[item.webhook])}
                  value={form[item.key]}
                  onChange={(value) => setForm((f) => ({ ...f, [item.key]: value }))}
                />
              ) : item.bool ? (
                <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={Boolean(form[item.key])}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, [item.key]: e.target.checked }))
                    }
                  />
                  {form[item.key] ? 'Увімкнено' : 'Вимкнено'}
                </label>
              ) : (
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
              )}
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
                    // Підказка своя для кожного ключа. Раніше текст про місто
                    // й відділення стояв під будь-яким секретом.
                    : `Не підключено. ${item.secretHint || ''}`}
                </p>
              )}
            </Field>
          ))}
          </div>
          {group.title === 'SalesDrive' && <>
            <div className="row" style={{ marginTop: 10 }}>
              <button type="button" className="btn ghost small" onClick={loadSalesDriveDictionaries} disabled={sdDictBusy}>
                {sdDictBusy ? 'Оновлення довідників…' : 'Оновити дані SalesDrive'}
              </button>
              <button type="button" className="btn ghost small" onClick={autoMapSalesDrive} disabled={!sdDicts.statuses.length}>
                Автозіставити
              </button>
              <span className={`chip ${sdDictError ? 'bad' : (sdDicts.statuses.length ? 'ok' : '')}`}>
                {sdDictError || (sdDicts.statuses.length ? `Завантажено: ${sdDicts.statuses.length} статусів, ${sdDicts.payments.length} оплат, ${sdDicts.deliveries.length} доставок` : 'Довідники ще не завантажено')}
              </span>
            </div>
            <SalesDriveCheck />
          </>}
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
