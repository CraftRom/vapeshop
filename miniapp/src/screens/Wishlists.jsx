import { useEffect, useState } from 'react'

import { api } from '../api'
import { alert, confirm, haptic, notify} from '../telegram'

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

  const toggle = async (list) => {
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
      setBusy(0)
    }
  }

  const create = async () => {
    const value = name.trim()
    if (!value) return
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
        <p className="hint" style={{ margin: '0 0 10px' }}>{product.name}</p>

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
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && create()}
              placeholder="Назва списку"
              autoFocus
            />
            <button className="add" onClick={create} disabled={busy === -1 || !name.trim()}>
              Створити
            </button>
          </div>
        ) : (
          <button className="chip" style={{ marginTop: 10 }} onClick={() => setCreating(true)}>
            + Новий список
          </button>
        )}
      </div>
    </div>
  )
}

export function Wishlists({ config, wishlists, cart, onChanged, onOpenProduct, onCartChange }) {
  const [renaming, setRenaming] = useState(null)
  const [name, setName] = useState('')
  const [error, setError] = useState('')

  // Повідомлення про помилку зникає, щойно перелік змінився: інакше воно
  // висить на екрані після успішної дії й виглядає так, ніби нічого не
  // спрацювало — саме це й було видно на екрані «Збережене».
  useEffect(() => { setError('') }, [wishlists])

  const qtyOf = (id) => cart?.lines?.find((l) => l.product_id === id)?.qty || 0

  const rename = async (list) => {
    const value = name.trim()
    if (!value || value === list.name) return setRenaming(null)
    try {
      onChanged(await api.wishlists.rename(list.id, value))
      setRenaming(null)
    } catch (err) {
      setError(err.message)
    }
  }

  const remove = async (list) => {
    if (!(await confirm(`Видалити список «${list.name}»? Товари залишаться в каталозі.`))) return
    try {
      await api.wishlists.remove(list.id)
      onChanged()
    } catch (err) {
      // Останній список видалити не можна — бекенд це стереже
      alert(err.message)
    }
  }

  const drop = async (list, product) => {
    haptic('light')
    try {
      onChanged(await api.wishlists.toggle(list.id, product.id))
    } catch (err) {
      setError(err.message)
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
    setError('')
    try {
      onChanged(await api.wishlists.create(`Список ${freeNumber(wishlists)}`))
    } catch (err) {
      // Перелік у пропсі міг застаріти: список створили в іншому місці
      // застосунку, а сюди оновлення ще не дійшло. Перепитуємо сервер і
      // пробуємо ще раз — це рівно та відповідь, яку людина й очікує.
      if (err.status !== 409) return setError(err.message)
      try {
        const fresh = await api.wishlists.list()
        onChanged(await api.wishlists.create(`Список ${freeNumber(fresh)}`))
      } catch (retry) {
        setError(retry.message)
      }
    }
  }

  return (
    <>
      <div className="head">
        <h1>Збережене</h1>
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
              <button
                className="wl-name"
                onClick={() => { setRenaming(list.id); setName(list.name) }}
                title="Перейменувати"
              >
                {list.name} <span className="hint num">· {list.size}</span>
              </button>
            )}
            <button className="chip" onClick={() => remove(list)}>Видалити</button>
          </div>

          {list.products.length === 0 ? (
            <p className="hint" style={{ padding: '0 14px 12px' }}>
              Порожньо. Відкрийте товар у каталозі й натисніть сердечко.
            </p>
          ) : (
            <div className="list">
              {list.products.map((p) => (
                <div className="card" key={p.id}>
                  <button className="card-body card-open" onClick={() => onOpenProduct(p)}>
                    <p className="card-title">{p.name}</p>
                    {p.description && <p className="card-note clamp">{p.description}</p>}
                    <div className="price num">
                      {Number(p.price).toFixed(0)} <small>{config.currency}</small>
                      {p.stock <= 0 && <span className="stock out"> · Немає</span>}
                    </div>
                  </button>
                  <div className="wl-actions">
                    <button
                      className="add"
                      disabled={p.stock <= 0 || qtyOf(p.id) >= p.stock}
                      onClick={() => onCartChange(p, 1)}
                    >
                      {qtyOf(p.id) > 0 ? `У кошику · ${qtyOf(p.id)}` : 'У кошик'}
                    </button>
                    <button className="chip" onClick={() => drop(list, p)}>Прибрати</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      <div className="screen">
        <button className="chip" onClick={create}>+ Новий список</button>
      </div>
    </>
  )
}
