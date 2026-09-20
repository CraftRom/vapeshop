import { useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { alert, confirm, haptic, notify} from '../telegram'
import { ProductCard } from './Catalog'

/** Чи лежить товар хоч в одному списку — для стану сердечка. */
export function isSaved(wishlists, productId) {
  return (wishlists || []).some((w) => w.product_ids.includes(productId))
}

/** Вибір списку при збереженні товару.
 *
 * Показуємо навіть коли список один: інакше при появі другого поведінка
 * кнопки змінилася б без попередження, а тут одразу видно, куди пішов товар.
 */
export function SavePicker({ product, wishlists, onClose, onChanged }) {
  const [busy, setBusy] = useState(0)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const actionRef = useRef(false)

  const toggle = async (list) => {
    if (actionRef.current) return
    actionRef.current = true
    setBusy(list.id)
    setError('')
    haptic('light')
    try {
      const updated = await api.wishlists.toggle(list.id, product.id)
      onChanged(updated)
      // Закриваємо вікно після додавання. Раніше воно лишалось відкритим,
      // і людина не розуміла, спрацювало чи ні: сердечко на картці під
      // модалкою не видно, підтвердження немає. При прибиранні з
      // останнього списку не закриваємо — видно, що товар зник із нього.
      const nowIn = (updated?.product_ids || []).includes(product.id)
      if (nowIn) {
        notify('success')
        onClose()
      }
    } catch (err) {
      setError(err.message)
    } finally {
      actionRef.current = false
      setBusy(0)
    }
  }

  const create = async () => {
    const value = name.trim()
    if (!value || actionRef.current) return
    actionRef.current = true
    setBusy(-1)
    setError('')
    try {
      let target
      try {
        target = await api.wishlists.create(value)
      } catch (err) {
        // Список із такою назвою вже є. Показувати помилку тут безглуздо:
        // людина хотіла покласти товар у список «Подарунки», і те, що він
        // уже створений, — не перешкода, а саме те, що потрібно.
        if (err.status !== 409) throw err
        const existing = await api.wishlists.list()
        target = (existing || []).find(
          (w) => w.name.trim().toLowerCase() === value.toLowerCase(),
        )
        if (!target) throw err
      }

      // Створювали список саме щоб покласти туди товар — кладемо одразу
      onChanged(await api.wishlists.toggle(target.id, product.id))
      setName('')
      setCreating(false)
      notify('success')
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      actionRef.current = false
      setBusy(0)
    }
  }

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <strong>Зберегти в список</strong>
          <button className="chip" onClick={onClose}>Закрити</button>
        </div>
        <p className="hint sheet-sub">{product.name}</p>

        {error && <div className="banner warn">{error}</div>}

        <div className="sheet-list">
          {wishlists.map((w) => {
            const inList = w.product_ids.includes(product.id)
            return (
              <button
                key={w.id}
                className={`sheet-row ${inList ? 'on' : ''}`}
                onClick={() => toggle(w)}
                disabled={busy === w.id}
              >
                <span className="mark">{inList ? '✓' : '+'}</span>
                <span className="grow">{w.name}</span>
                <span className="hint num">{w.size}</span>
              </button>
            )
          })}
        </div>

        {creating ? (
          <div className="inline-field sheet-create">
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && create()}
              placeholder="Назва списку"
              autoFocus
            />
            <button className="primary" onClick={create} disabled={busy === -1 || !name.trim()}>
              Створити
            </button>
          </div>
        ) : (
          <button className="secondary sheet-create" onClick={() => setCreating(true)}>
            + Новий список
          </button>
        )}
      </div>
    </div>
  )
}

export function Wishlists({ wishlists, onChanged, onOpenList }) {
  const [renaming, setRenaming] = useState(null)
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const actionRef = useRef(false)

  // Повідомлення про помилку зникає, щойно перелік змінився: інакше воно
  // висить на екрані після успішної дії й виглядає так, ніби нічого не
  // спрацювало — саме це й було видно на екрані «Збережене».
  useEffect(() => { setError('') }, [wishlists])

  const rename = async (list) => {
    const value = name.trim()
    if (!value || value === list.name) return setRenaming(null)
    if (actionRef.current) return
    actionRef.current = true
    try {
      onChanged(await api.wishlists.rename(list.id, value))
      setRenaming(null)
    } catch (err) {
      setError(err.message)
    } finally {
      actionRef.current = false
    }
  }

  const remove = async (list) => {
    if (actionRef.current) return
    if (!(await confirm(`Видалити список «${list.name}»? Товари залишаться в каталозі.`))) return
    actionRef.current = true
    try {
      await api.wishlists.remove(list.id)
      onChanged()
    } catch (err) {
      // Останній список видалити не можна — бекенд це стереже
      await alert(err.message)
    } finally {
      actionRef.current = false
    }
  }

  /** Вільний номер за переліком назв. */
  const freeNumber = (lists) => {
    // Порівнюємо нормалізовані назви: «Список 2» і «список  2» — те саме
    // для сервера, і саме на цьому раніше виникав збіг.
    const taken = new Set(
      (lists || []).map((w) => w.name.trim().toLowerCase().replace(/\s+/g, ' ')),
    )
    let n = 1
    while (taken.has(`список ${n}`)) n += 1
    return n
  }

  const create = async () => {
    if (actionRef.current) return
    actionRef.current = true
    setError('')
    try {
      onChanged(await api.wishlists.create(`Список ${freeNumber(wishlists)}`))
    } catch (err) {
      // Перелік у пропсі міг застаріти: список створили в іншому місці
      // застосунку, а сюди оновлення ще не дійшло. Перепитуємо сервер і
      // пробуємо ще раз — це рівно та відповідь, яку людина й очікує.
      if (err.status !== 409) {
        setError(err.message)
        return
      }
      try {
        const fresh = await api.wishlists.list()
        onChanged(await api.wishlists.create(`Список ${freeNumber(fresh)}`))
      } catch (retry) {
        setError(retry.message)
      }
    } finally {
      actionRef.current = false
    }
  }

  return (
    <>
      {/* Розділ усередині профілю, тож заголовок другого рівня: сторінкою
          «Збережене» стає лише тоді, коли відкривають конкретний список. */}
      <div className="section-head">
        <h2>Збережене</h2>
        <p>Товари, які ви відклали на потім</p>
      </div>

      {error && <div className="banner warn">{error}</div>}

      {(wishlists || []).map((list) => (
        <div className="wl" key={list.id}>
          <div className="wl-head">
            {renaming === list.id ? (
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onBlur={() => rename(list)}
                onKeyDown={(e) => e.key === 'Enter' && rename(list)}
                autoFocus
              />
            ) : (
              /* Дотик по назві відкриває список, а не перейменовує його.
                 Перейменування раніше стояло на найбільшій цілі екрана —
                 людина тикала в назву, щоб подивитись уміст, і потрапляла
                 в поле вводу. Перейменування тепер окремою дією нижче. */
              <button
                className="wl-name"
                onClick={() => onOpenList(list)}
                title="Відкрити список"
              >
                <span className="grow">{list.name}</span>
                <span className="wl-size num">{list.size}</span>
              </button>
            )}
          </div>

          <div className="wl-actions">
            <button className="secondary" onClick={() => onOpenList(list)}>Відкрити</button>
            <button
              className="secondary"
              onClick={() => { setRenaming(list.id); setName(list.name) }}
            >
              Перейменувати
            </button>
            <button className="ghost-btn" onClick={() => remove(list)}>Видалити</button>
          </div>

          {list.size === 0 && (
            <p className="hint wl-empty">
              Порожньо. Відкрийте товар у каталозі й натисніть «Відкласти».
            </p>
          )}
        </div>
      ))}

      <div className="screen">
        <button className="secondary" onClick={create}>Новий список</button>
      </div>
    </>
  )
}


/** Окрема сторінка одного списку.
 *
 * Товари показані тими самими картками, що й у каталозі: лічильник
 * кількості, стара ціна, значок знижки, залишок. Раніше «Збережене»
 * малювало власний спрощений варіант, і той самий товар виглядав
 * по-різному залежно від того, звідки на нього дивишся.
 */
export function WishlistPage({ config, list, cart, onChanged, onOpenProduct, onCartChange }) {
  const [error, setError] = useState('')
  const droppingRef = useRef(new Set())

  useEffect(() => { setError('') }, [list])

  const qtyOf = (id) => cart?.lines?.find((l) => l.product_id === id)?.qty || 0

  const drop = async (product) => {
    if (droppingRef.current.has(product.id)) return
    droppingRef.current.add(product.id)
    haptic('light')
    try {
      onChanged(await api.wishlists.toggle(list.id, product.id))
    } catch (err) {
      setError(err.message)
    } finally {
      droppingRef.current.delete(product.id)
    }
  }

  const products = list.products || []

  return (
    <>
      <div className="head">
        <h1>{list.name}</h1>
        <p>
          {products.length === 0
            ? 'Поки порожньо'
            : `${products.length} ${products.length === 1 ? 'товар'
                : products.length < 5 ? 'товари' : 'товарів'}`}
        </p>
      </div>

      {error && <div className="banner warn">{error}</div>}

      {products.length === 0 ? (
        <div className="empty">
          <p>Тут нічого немає.</p>
          <p className="hint">
            Відкрийте каталог і натисніть «Відкласти» під потрібним товаром.
          </p>
        </div>
      ) : (
        <div className="list">
          {products.map((p) => (
            <ProductCard
              key={p.id}
              product={p}
              qty={qtyOf(p.id)}
              currency={config.currency}
              onChange={onCartChange}
              onOpen={onOpenProduct}
              saved
              saveLabel="✕ Прибрати"
              onSave={drop}
            />
          ))}
        </div>
      )}
    </>
  )
}
