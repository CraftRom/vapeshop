from __future__ import annotations
import io, re, secrets, string, zipfile
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


class RowError(ValueError):
    """One spreadsheet cell is unusable; only its row is rejected."""


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def price_cell(v, column):
    """Money: finite, non-negative, at most 2 decimals. Never silently dropped."""
    if _blank(v):
        return None
    if isinstance(v, bool):
        raise RowError(f'{column}: очікується число')
    text = str(v).strip().replace(' ', '').replace('\u00a0', '').replace(',', '.')
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        raise RowError(f'{column}: «{str(v)[:40]}» не є числом') from None
    if not value.is_finite():
        raise RowError(f'{column}: значення має бути скінченним числом')
    if value < 0:
        raise RowError(f'{column}: від’ємна ціна')
    if value != value.quantize(Decimal('0.01')):
        raise RowError(f'{column}: більше двох знаків після коми')
    if value >= Decimal('100000000'):
        raise RowError(f'{column}: завелике значення')
    return value.quantize(Decimal('0.01'))


def stock_cell(v):
    """Stock is a whole non-negative count: 1.9 is an error, not 1."""
    if _blank(v):
        return None
    if isinstance(v, bool):
        raise RowError('Залишок: очікується ціле число')
    try:
        value = Decimal(str(v).strip().replace(' ', '').replace('\u00a0', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        raise RowError(f'Залишок: «{str(v)[:40]}» не є цілим числом') from None
    if not value.is_finite() or value != value.to_integral_value():
        raise RowError('Залишок: потрібне ціле число без дробової частини')
    if value < 0:
        raise RowError('Залишок не може бути від’ємним')
    if value > 1_000_000:
        raise RowError('Залишок: завелике значення')
    return int(value)

def parse_salesdrive_xlsx(raw: bytes):
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError('XLSX більший за 10 МБ')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(x.file_size for x in entries) > 64 * 1024 * 1024 or any(x.flag_bits & 1 for x in entries):
                raise ValueError('XLSX перевищує межі розпакування')
    except zipfile.BadZipFile:
        raise ValueError('Пошкоджений XLSX')
    wb=load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        rows=wb.active.iter_rows(values_only=True)
        headers=[str(x or '').strip() for x in next(rows, ())]
        idx={h:i for i,h in enumerate(headers)}
        name_key='Товар/Послуга' if 'Товар/Послуга' in idx else 'Товар'
        if name_key not in idx:
            raise ValueError('Немає колонки Товар/Послуга або Товар')
        out=[]
        for number, r in enumerate(rows, 1):
            if number > 50000:
                raise ValueError("XLSX містить понад 50 000 рядків")
            def get(k): return r[idx[k]] if k in idx and idx[k] < len(r) else None
            def flag(k):
                value=get(k)
                if value is None: return None
                return str(value).strip().lower() in {'так','true','1','yes'}
            name=str(get(name_key) or '').strip()
            if not name: continue
            row_number=number+1
            try:
                current=price_cell(get('Ціна'),'Ціна'); old=price_cell(get('Стара ціна'),'Стара ціна')
                discount=price_cell(get('Ціна зі знижкою'),'Ціна зі знижкою')
                stock=stock_cell(get('Залишок'))
            except RowError as exc:
                # One bad cell must not abort the whole file or be guessed.
                out.append({'row':row_number,'name':name,'error':str(exc)})
                continue
            own='Субкатегорія' in idx
            out.append({'row':row_number,'name':name,'sku':get('SKU'),'external_sku':get('Зовнішній артикул'),'category':str(get('Категорія') or '').strip(),
                        'subcategory':str(get('Субкатегорія') or '').strip(), 'hierarchy':own,
                        'subcategory_parent':str(get('Батьківська категорія субкатегорії') or '').strip(),
                        'description':get('Опис'),'photo_url':get('Зображення'),
                        'current_price':current,'old_price':old,
                        'regular_price':old if own and old is not None else current,
                        'discount_price':current if own and old is not None else discount,
                        'stock':stock,
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
