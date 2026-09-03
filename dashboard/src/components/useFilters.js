import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Фільтри, які живуть в адресі сторінки, а не всередині компонента.
 *
 * Проблема була щоденною і непомітною в коді. Менеджер відбирає
 * «Прийняті» за минулий тиждень, відкриває замовлення, повертається — і
 * бачить «Усі» з початку. Фільтр лежав у useState, а useState зникає
 * разом із компонентом при переході на сторінку замовлення. За зміну
 * таких повернень десятки, і кожне коштує чотирьох дій заново.
 *
 * Адреса сторінки виправляє це сама собою й дає ще три речі:
 *
 *   • Кнопка «назад» у браузері працює як очікують: повертає до
 *     попереднього відбору, а не просто на сторінку.
 *   • Відбір можна надіслати іншому менеджеру посиланням.
 *   • Оновлення сторінки (F5) не втрачає роботу — на повільному
 *     зʼєднанні це трапляється частіше, ніж здається.
 *
 * Значення за замовчуванням в адресу не пишемо: «/orders» замість
 * «/orders?status=&search=&dateFrom=&dateTo=» — і читати легше, і при
 * копіюванні посилання не тягне за собою порожнечу.
 *
 * @param defaults {object} назва фільтра → значення за замовчуванням
 * @returns [значення, встановити(назва, значення), скинути()]
 */
export function useFilters(defaults) {
  const [params, setParams] = useSearchParams()

  const values = useMemo(() => {
    const out = {}
    for (const [key, fallback] of Object.entries(defaults)) {
      const raw = params.get(key)
      if (raw === null) {
        out[key] = fallback
      } else if (typeof fallback === 'number') {
        // Число з адреси приходить рядком. Без перетворення
        // «limit=500» поїхав би у запит як текст, а порівняння з
        // варіантами випадного списку перестало б збігатися.
        const parsed = Number(raw)
        out[key] = Number.isFinite(parsed) ? parsed : fallback
      } else {
        out[key] = raw
      }
    }
    return out
    // params — новий обʼєкт на кожен рендер, тож залежність по рядку
  }, [params.toString()]) // eslint-disable-line react-hooks/exhaustive-deps

  const set = useCallback((key, value) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      if (value === '' || value === null || value === undefined
          || value === defaults[key]) {
        next.delete(key)
      } else {
        next.set(key, String(value))
      }
      return next
      // replace: зміна фільтра не має додавати запис в історію браузера.
      // Інакше після п'яти уточнень «назад» треба тиснути п'ять разів,
      // щоб просто піти зі сторінки.
    }, { replace: true })
  }, [setParams, defaults])

  const reset = useCallback(() => {
    setParams(new URLSearchParams(), { replace: true })
  }, [setParams])

  return [values, set, reset]
}
