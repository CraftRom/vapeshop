/**
 * Замовлення йде однією послідовністю, тому статус показано доріжкою
 * етапів: видно і де воно зараз, і скільки шляху позаду. Клік по етапу
 * переводить замовлення туди.
 *
 * Сама послідовність залежить від способу оплати. При оплаті на картку
 * «Оплачено» — окремий крок: гроші приходять до відправки, і менеджер має
 * бачити, чи вони вже надійшли. При накладеному платежі такого кроку не
 * існує — клієнт платить у відділенні при отриманні, тобто оплата й
 * виконання це та сама подія. Показувати його означало б просити
 * менеджера відзначати те, чого він не бачить.
 */

const CARD_STAGES = [
  { key: 'new', label: 'Нове' },
  { key: 'accepted', label: 'Прийн.' },
  { key: 'paid', label: 'Оплач.' },
  { key: 'shipped', label: 'Відпр.' },
  { key: 'done', label: 'Викон.' },
]

const COD_STAGES = [
  { key: 'new', label: 'Нове' },
  { key: 'accepted', label: 'Прийн.' },
  { key: 'shipped', label: 'Відпр.' },
  { key: 'done', label: 'Викон.' },
]

/** Кроки доріжки для способу оплати. Дзеркало stages_for з бекенду. */
export function stagesFor(paymentMethod) {
  return paymentMethod === 'cod' ? COD_STAGES : CARD_STAGES
}

// Лишається для коду, який показує статус, не знаючи способу оплати.
export const STAGES = CARD_STAGES

export const STATUS_LABELS = {
  new: 'Нове',
  // Кроку більше немає в маршруті, але він лишився в базі на замовленнях,
  // яких не зачепила міграція. Без підпису вони показувалися б порожнім
  // місцем замість статусу.
  confirmed: 'Підтверджене',
  accepted: 'Прийняте в роботу',
  paid: 'Оплачене',
  shipped: 'Відправлене',
  done: 'Виконане',
  cancelled: 'Скасоване',
}

// Дзеркало route_for з бекенду. Без нього доріжка пропонувала б переходи,
// які сервер відхилить — менеджер бачив би 409 після кліку.
const CARD_ALLOWED = {
  new: ['accepted', 'cancelled'],
  accepted: ['paid', 'cancelled'],
  paid: ['shipped', 'cancelled'],
  shipped: ['done', 'cancelled'],
  done: [],
  cancelled: [],
  confirmed: ['accepted', 'cancelled'],
}

const COD_ALLOWED = {
  new: ['accepted', 'cancelled'],
  accepted: ['shipped', 'cancelled'],
  shipped: ['done', 'cancelled'],
  done: [],
  cancelled: [],
  confirmed: ['accepted', 'cancelled'],
  // Спадок: до поділу маршрутів замовлення з накладеним платежем могло
  // застрягти в «Оплачено». Лишаємо йому вихід уперед.
  paid: ['shipped', 'cancelled'],
}

export function allowedFrom(status, paymentMethod) {
  const table = paymentMethod === 'cod' ? COD_ALLOWED : CARD_ALLOWED
  return table[status] || []
}

export default function StatusRail({ status, paymentMethod, onChange, disabled = false }) {
  if (status === 'cancelled') {
    // Повернути скасоване не можна: скасування вже повернуло залишки
    // на склад і бонуси клієнту, а повторне списання зіпсувало б облік
    return (
      <div className="rail">
        <button className="cancelled" disabled style={{ borderRadius: 8 }}>
          Скасоване
        </button>
      </div>
    )
  }

  if (status === 'done') {
    return (
      <div className="rail">
        <button className="passed" disabled style={{ borderRadius: 8 }}>
          Виконане
        </button>
      </div>
    )
  }

  const stages = stagesFor(paymentMethod)
  const allowed = allowedFrom(status, paymentMethod)
  let currentIndex = stages.findIndex((s) => s.key === status)

  // Спадкові статуси в доріжці не показані. Щоб замовлення в такому стані
  // не виглядало так, ніби воно на самому початку, вважаємо пройденим усе
  // до найближчого кроку, куди воно ще може перейти.
  if (currentIndex < 0) {
    const nextIndex = stages.findIndex((s) => allowed.includes(s.key))
    currentIndex = nextIndex < 0 ? -1 : nextIndex - 0.5
  }

  return (
    <div className="rail">
      {stages.map((stage, index) => {
        const state = index < currentIndex ? 'passed' : index === currentIndex ? 'current' : ''
        const reachable = allowed.includes(stage.key)
        return (
          <button
            key={stage.key}
            className={state}
            disabled={disabled || index === currentIndex || !reachable}
            onClick={() => onChange(stage.key)}
            title={
              index === currentIndex
                ? 'Поточний статус'
                : reachable
                  ? `Перевести в «${STATUS_LABELS[stage.key]}»`
                  : 'Недоступно з поточного статусу'
            }
          >
            {stage.label}
          </button>
        )
      })}
    </div>
  )
}
