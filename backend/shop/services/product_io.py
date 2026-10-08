from __future__ import annotations
import io, re, secrets, string
from decimal import Decimal, InvalidOperation
from openpyxl import load_workbook, Workbook

SKU_RE = re.compile(r'^[A-Z0-9][A-Z0-9._-]{2,31}$')

def normalize_sku(value) -> str | None:
    if value is None: return None
    sku=str(value).strip().upper()
    return sku if SKU_RE.fullmatch(sku) else None

def category_code(name: str) -> str:
    chars=''.join(c for c in str(name).upper() if c in string.ascii_uppercase+string.digits)
    return (chars[:4] or 'GEN').ljust(3,'X')

async def generate_sku(repo, category_name='GEN') -> str:
    prefix=f'ELF-{category_code(category_name)}-'
    alphabet=string.ascii_uppercase+string.digits
    for _ in range(50):
        sku=prefix+''.join(secrets.choice(alphabet) for _ in range(8))
        if not await repo.get_product_by_sku(sku): return sku
    raise RuntimeError('Не вдалося згенерувати унікальний артикул')

def dec(v):
    try: return Decimal(str(v)) if v not in (None,'') else None
    except (InvalidOperation, ValueError): return None

def parse_salesdrive_xlsx(raw: bytes):
    wb=load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        rows=wb.active.iter_rows(values_only=True)
        headers=[str(x or '').strip() for x in next(rows, ())]
        idx={h:i for i,h in enumerate(headers)}
        name_key='Товар/Послуга' if 'Товар/Послуга' in idx else 'Товар'
        if name_key not in idx:
            raise ValueError('Немає колонки Товар/Послуга або Товар')
        out=[]
        for r in rows:
            def get(k): return r[idx[k]] if k in idx and idx[k] < len(r) else None
            def flag(k):
                value=get(k)
                if value is None: return None
                return str(value).strip().lower() in {'так','true','1','yes'}
            name=str(get(name_key) or '').strip()
            if not name: continue
            current=dec(get('Ціна')); old=dec(get('Стара ціна'))
            own='Субкатегорія' in idx
            out.append({'name':name,'sku':get('SKU'),'external_sku':get('Зовнішній артикул'),'category':str(get('Категорія') or '').strip(),
                        'subcategory':str(get('Субкатегорія') or '').strip(), 'hierarchy':own,
                        'subcategory_parent':str(get('Батьківська категорія субкатегорії') or '').strip(),
                        'description':get('Опис'),'photo_url':get('Зображення'),
                        'current_price':current,'old_price':old,
                        'regular_price':old if own and old is not None else current,
                        'discount_price':current if own and old is not None else dec(get('Ціна зі знижкою')),
                        'stock':int(get('Залишок')) if get('Залишок') is not None else None,
                        'is_active':flag('Активний'),'is_new':flag('Новинка'),'is_sale':flag('Акція')})
        return out
    finally:
        wb.close()


def export_xlsx(products, subcategories=()):
    wb=Workbook(); ws=wb.active; ws.title='Products'
    ws.append(['SKU','Товар','Категорія','Субкатегорія','Батьківська категорія субкатегорії','Ціна','Стара ціна','Залишок','Опис','Зображення','Активний','Новинка','Акція','Зовнішній артикул'])
    parents={s.id:s.category_name for s in subcategories}
    for p in products:
        values=[p.sku,p.name,p.category_name,p.subcategory_name,parents.get(p.subcategory_id),
                float(p.price),float(p.old_price) if p.old_price is not None else None,p.stock,
                p.description,p.photo_url,'Так' if p.is_active else 'Ні',
                'Так' if p.is_new else 'Ні','Так' if p.is_sale else 'Ні',p.external_sku]
        ws.append(values)
        # User names/descriptions are strings, not executable spreadsheet formulae.
        for cell in ws[ws.max_row]:
            if isinstance(cell.value, str): cell.data_type='s'
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width=min(48,max(12,max(len(str(c.value or '')) for c in col)+2))
    ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
    b=io.BytesIO(); wb.save(b); return b.getvalue()
