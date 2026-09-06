/** Поле, яке малює своє значення саме.
 *
 * Чому так, а не звичайним полем.
 *
 * Діагностика на живому телефоні дала два факти поруч. Перший: у полі
 * все правильно — білий текст на темній підкладці, непрозорість
 * одиниця, шрифт 16px, прокрутки немає, каретка стоїть після
 * тринадцятого символа з тринадцяти, жодного стороннього припису й
 * жодної чужої таблиці стилів. Другий: той самий рядок, тим самим
 * кольором, у звичайному блоці поруч — читається.
 *
 * Тобто цей WebView не малює гліфи саме в полі введення. Не в темі, не
 * в кольорі, не в React — у самому полі. Сім спроб виправити стилі
 * нічого не дали, бо виправляти в них не було чого.
 *
 * Тому значення малює блок, а поле лишається невидимим під ним: воно
 * приймає введення, тримає каретку й віддає значення, але свій текст не
 * показує. Малює те, що на цьому пристрої точно малюється.
 *
 * Ціна рішення, щоб її не шукали як поломку:
 *  — виділення тексту видно як підсвітку, але без інверсії кольору;
 *  — довгий рядок доводиться прокручувати разом із полем, тому нижче
 *    прокрутка блока прив'язана до прокрутки поля;
 *  — поки клавіатура набирає слово «композицією», у блоці видно вже
 *    введені літери, а незавершене слово підказує сама клавіатура.
 */
import { useEffect, useRef } from 'react'

export function Field({ value = '', multiline = false, className = 'input', ...rest }) {
  const host = useRef(null)
  const echo = useRef(null)

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
  }, [value])

  const Tag = multiline ? 'textarea' : 'input'
  return (
    <div className="field-paint">
      <Tag ref={host} className={`${className} ghost`} value={value} {...rest} />
      {/* aria-hidden: для читача екрана значення вже є в самому полі,
          і друга копія читалася б двічі. */}
      <div
        ref={echo}
        aria-hidden="true"
        className={multiline ? 'echo echo-multiline' : 'echo'}
      >
        {value}
      </div>
    </div>
  )
}
