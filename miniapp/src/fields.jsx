/** Поле, яке малює своє значення саме.
 *
 * Telegram WebView на частині Android-пристроїв губить гліфи всередині
 * самого input/textarea. Значення тому малює окремий echo-шар, а нативне
 * поле лишається джерелом вводу, каретки й accessibility.
 *
 * Важливо: саме поле НЕКЕРОВАНЕ. React не присвоює йому value на кожному
 * рендері, бо таке присвоєння під час IME-композиції Android скидає
 * незавершене слово. Свої зміни ми віддаємо назовні, але назад у DOM не
 * записуємо; лише справжня зовнішня зміна (вибір міста, reset форми) має
 * право програмно змінити el.value.
 */
import { useEffect, useRef, useState } from 'react'

export function Field({
  value = '', multiline = false, className = 'input', onChange, ...rest
}) {
  const host = useRef(null)
  const echo = useRef(null)
  const mine = useRef(String(value ?? ''))
  const [painted, setPainted] = useState(String(value ?? ''))

  // Синхронізуємо тільки зміни, які прийшли НЕ від цього самого поля.
  // Якщо батько просто повернув щойно набраний текст як prop, DOM уже має
  // правильне значення — повторний запис лише ламає мобільну композицію.
  useEffect(() => {
    const el = host.current
    if (!el) return
    if (value === mine.current) return
    mine.current = value
    el.value = value
    setPainted(String(value ?? ''))
  }, [value])

  const report = (event) => {
    mine.current = event.target.value
    setPainted(event.target.value)
    onChange?.(event)
  }

  // Поле може бути ширшим за екран — тоді воно прокручується всередині
  // себе. Блок мусить їхати разом із ним, інакше видно початок рядка,
  // коли набирають кінець.
  useEffect(() => {
    const input = host.current
    const layer = echo.current
    if (!input || !layer) return undefined
    const sync = () => {
      layer.scrollLeft = input.scrollLeft
      layer.scrollTop = input.scrollTop
    }
    sync()
    input.addEventListener('scroll', sync)
    input.addEventListener('input', sync)
    input.addEventListener('keyup', sync)
    return () => {
      input.removeEventListener('scroll', sync)
      input.removeEventListener('input', sync)
      input.removeEventListener('keyup', sync)
    }
  }, [])

  const Tag = multiline ? 'textarea' : 'input'
  return (
    <div className="field-paint">
      <Tag
        ref={host}
        className={`${className} ghost`}
        defaultValue={value}
        onChange={report}
        {...rest}
      />
      {/* aria-hidden: для читача екрана значення вже є в самому полі,
          і друга копія читалася б двічі. */}
      <div
        ref={echo}
        aria-hidden="true"
        className={multiline ? 'echo echo-multiline' : 'echo'}
      >
        {painted}
      </div>
    </div>
  )
}
