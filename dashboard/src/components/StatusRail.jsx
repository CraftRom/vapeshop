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

export default function StatusRail({ status, onChange, disabled = false }) {
  if (status === 'cancelled') {
    return (
      <div className="rail">
        <button className="cancelled" disabled style={{ borderRadius: 8 }}>
          Скасоване
        </button>
        {!disabled && (
          <button onClick={() => onChange('new')} title="Повернути в роботу" style={{ flex: '0 0 34px' }}>
            ↺
          </button>
        )}
      </div>
    )
  }

  const currentIndex = STAGES.findIndex((s) => s.key === status)

  return (
    <div className="rail">
      {STAGES.map((stage, index) => {
        const state = index < currentIndex ? 'passed' : index === currentIndex ? 'current' : ''
        return (
          <button
            key={stage.key}
            className={state}
            disabled={disabled || index === currentIndex}
            onClick={() => onChange(stage.key)}
            title={`Перевести в «${STATUS_LABELS[stage.key]}»`}
          >
            {stage.label}
          </button>
        )
      })}
    </div>
  )
}
