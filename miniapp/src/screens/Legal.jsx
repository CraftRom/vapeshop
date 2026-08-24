import { useState } from 'react'

import { DOCUMENTS, LEGAL_UPDATED, documentText, sellerIncomplete } from '../legal'
import { APP_VERSION, AUTHOR } from '../version'

/** Розмітка документів обмежена <b> — тому просте, передбачуване
 *  перетворення замість підключення парсера заради двох тегів. */
function Paragraphs({ text }) {
  return text.split('\n\n').map((block, i) => {
    const bold = block.match(/^<b>(.*)<\/b>$/)
    if (bold) return <h3 key={i} className="legal-h">{bold[1]}</h3>
    return <p key={i} className="legal-p">{block}</p>
  })
}

export function Legal({ config, initial, onBack }) {
  const [open, setOpen] = useState(initial || null)
  const seller = config?.seller || {}
  const gaps = sellerIncomplete(seller)

  if (open) {
    const doc = DOCUMENTS.find((d) => d.key === open)
    return (
      <div className="screen legal">
        <button className="chip" onClick={() => setOpen(null)}>← Документи</button>
        <h1 className="legal-title">{doc.title}</h1>
        <p className="hint">Редакція від {LEGAL_UPDATED}</p>

        {gaps.length > 0 && (
          <div className="banner warn">
            Документ неповний: продавець ще не вказав реквізити. Перед покупкою
            уточніть їх в оператора.
          </div>
        )}

        <Paragraphs text={documentText(open, seller)} />

        <p className="hint" style={{ marginTop: 20 }}>
          Питання щодо умов — оператору в чаті замовлення
          {seller.SELLER_EMAIL ? ` або на ${seller.SELLER_EMAIL}` : ''}.
        </p>
      </div>
    )
  }

  return (
    <>
      <div className="head">
        {onBack && <button className="chip" onClick={onBack} style={{ marginBottom: 8 }}>← Назад</button>}
        <h1>Умови та документи</h1>
        <p>Правила покупки, обробка даних і повернення</p>
      </div>

      {gaps.length > 0 && (
        <div className="banner warn" style={{ margin: '0 14px 12px' }}>
          Реквізити продавця не заповнені — документи показані як заготовка.
        </div>
      )}

      <div className="screen">
        {DOCUMENTS.map((d) => (
          <button key={d.key} className="legal-row" onClick={() => setOpen(d.key)}>
            <span className="grow">{d.title}</span>
            <span className="hint">›</span>
          </button>
        ))}
      </div>

      <Footer />
    </>
  )
}

/** Підвал вітрини. Версія тут своя — панель керування має власну. */
export function Footer({ onLegal }) {
  return (
    <div className="footer">
      {onLegal && (
        <button className="footer-link" onClick={onLegal}>
          Умови, оферта та повернення
        </button>
      )}
      <div className="hint num">
        Вітрина v{APP_VERSION} · {AUTHOR}
      </div>
    </div>
  )
}
