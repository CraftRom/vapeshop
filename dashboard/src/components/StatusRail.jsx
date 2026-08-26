/**
 * Замовлення завжди йде однією й тією ж послідовністю, тому статус показано
 * доріжкою етапів: видно і де замовлення зараз, і скільки шляху позаду.
 * Клік по етапу переводить замовлення туди.
 */

export const STAGES = [
  { key: 'new', label: 'Нове' },
  { key: 'confirmed', label: 'Підтв.' },
  { key: 'accepted', label: 'Прийн.' },
  { key: 'paid', label: 'Оплач.' },
  { key: 'shipped', label: 'Відпр.' },
  { key: 'done', label: 'Викон.' },
]

export const STATUS_LABELS = {
  new: 'Нове',
  confirmed: 'Підтверджене',
  accepted: 'Прийняте в роботу',
  paid: 'Оплачене',
  shipped: 'Відправлене',
  done: 'Виконане',
  cancelled: 'Скасоване',
}

// Дзеркало ALLOWED_TRANSITIONS з бекенду. Без нього доріжка пропонувала б
// переходи, які сервер відхилить — менеджер бачив би 409 після кліку.
const ALLOWED = {
  new: ['confirmed', 'cancelled'],
  confirmed: ['accepted', 'cancelled'],
  accepted: ['paid', 'shipped', 'cancelled'],
  paid: ['shipped', 'cancelled'],
  shipped: ['done', 'cancelled'],
  done: [],
  cancelled: [],
}

export default function StatusRail({ status, onChange, disabled = false }) {
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

  const currentIndex = STAGES.findIndex((s) => s.key === status)

  return (
    <div className="rail">
      {STAGES.map((stage, index) => {
        const state = index < currentIndex ? 'passed' : index === currentIndex ? 'current' : ''
        const reachable = (ALLOWED[status] || []).includes(stage.key)
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
