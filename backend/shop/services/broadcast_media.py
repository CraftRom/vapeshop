"""Read local images directly; Telegram must never receive our /media path as a file ID."""
from functools import lru_cache
from io import BytesIO
from PIL import Image, ImageOps

from shop.services.broadcast_content import media_path


@lru_cache(maxsize=12)
def _jpeg(path, modified, size):
    try:
        if size > 8 * 1024 * 1024:
            raise ValueError('Файл зображення перевищує 8 МБ')
        with Image.open(path, formats=['JPEG', 'PNG', 'WEBP', 'GIF']) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError('Зображення перевищує 20 Мп')
            image.seek(0)
            frame = ImageOps.exif_transpose(image).convert('RGBA')
            frame.thumbnail((2560, 2560))
            # Telegram rejects photo aspect ratios above 20:1. Pad extreme images.
            width, height = frame.size
            canvas = Image.new('RGB', (max(width, (height + 19) // 20), max(height, (width + 19) // 20)), 'white')
            canvas.paste(frame, ((canvas.width-width)//2, (canvas.height-height)//2), frame)
            output = BytesIO()
            canvas.save(output, format='JPEG', quality=88, optimize=True)
            return output.getvalue()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Не вдалося прочитати зображення. Завантажте його знову') from exc


def telegram_photo(value):
    path = media_path(value)
    if path is None:
        return None
    stat = path.stat()
    return _jpeg(str(path), stat.st_mtime_ns, stat.st_size)
