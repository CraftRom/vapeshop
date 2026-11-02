"""Validate Telegram content before committing a broadcast or contacting recipients."""
from html.parser import HTMLParser
import re
from urllib.parse import unquote, urlsplit

from shop.config import settings

TAGS = {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'a', 'code', 'pre', 'blockquote', 'tg-spoiler', 'span', 'tg-emoji'}


def valid_url(value, *, button=False):
    try:
        parts = urlsplit(value)
        return (parts.scheme in ({'http', 'https', 'tg'} if button else {'http', 'https'})
                and bool(parts.hostname) and not parts.username and not parts.password
                and not any(c.isspace() or ord(c) < 32 for c in value))
    except ValueError:
        return False


class TelegramHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag not in TAGS:
            raise ValueError(f'HTML-тег <{tag}> не підтримується. Для звичайного тексту виберіть режим «Текст»')
        allowed = {'a': {'href'}, 'span': {'class'}, 'code': {'class'}, 'blockquote': {'expandable'}, 'tg-emoji': {'emoji-id'}}.get(tag, set())
        if set(values) - allowed:
            raise ValueError(f'Непідтримувані атрибути HTML-тега <{tag}>')
        if tag == 'a' and not (valid_url(values.get('href', ''), button=True) or values.get('href', '').startswith('mailto:')):
            raise ValueError('HTML-посилання має містити коректний href')
        if tag == 'span' and values.get('class') != 'tg-spoiler':
            raise ValueError('Для <span> підтримується лише class="tg-spoiler"')
        if tag == 'code' and values.get('class') and (not self.stack or self.stack[-1] != 'pre' or not re.fullmatch(r'language-[A-Za-z0-9_+-]+', values['class'])):
            raise ValueError('Клас мови дозволено лише для <pre><code class="language-…">')
        if tag == 'tg-emoji' and not str(values.get('emoji-id', '')).isdigit():
            raise ValueError('Некоректний emoji-id')
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError('HTML-теги мають бути правильно вкладені й закриті')

    def handle_startendtag(self, tag, attrs):
        raise ValueError('Самозакривні HTML-теги не підтримуються. Для нового рядка натисніть Enter')

    def handle_data(self, data):
        self.parts.append(data)

    def handle_comment(self, data):
        raise ValueError('HTML-коментарі не підтримуються')

    def handle_decl(self, decl):
        raise ValueError('HTML-декларації не підтримуються')


def visible_text(text, text_format='plain'):
    if text_format == 'plain':
        return text
    if text_format != 'html':
        raise ValueError('Оберіть режим «Текст» або «HTML»')
    if re.search(r'&(?!(?:lt|gt|amp|quot|#\d+|#x[0-9a-fA-F]+);)', text):
        raise ValueError('У режимі HTML замініть символ & на &amp;')
    parser = TelegramHTML()
    parser.feed(text)
    parser.close()
    if parser.stack:
        raise ValueError('Закрийте всі HTML-теги повідомлення')
    if re.search(r'<(?!/?[a-zA-Z][^<>]*>)', text):
        raise ValueError('У режимі HTML замініть символ < на &lt;')
    return ''.join(parser.parts)


def local_media_name(value):
    """Resolve only our own media URLs, never arbitrary filesystem paths."""
    if not value:
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme or parts.netloc:
            host = (urlsplit(settings.public_url).hostname or '').removeprefix('www.')
            if parts.scheme not in {'http', 'https'} or not host or (parts.hostname or '').removeprefix('www.') != host:
                return None
        path = unquote(parts.path)
        if re.fullmatch(r'/media/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|gif|webp)', path, re.I):
            return path.rsplit('/', 1)[-1]
    except ValueError:
        pass
    return None


def media_path(value):
    from shop.paths import media_dir
    name = local_media_name(value)
    if not name:
        return None
    path = media_dir() / name
    if path.is_symlink() or not path.is_file():
        raise ValueError('Зображення відсутнє у сховищі. Завантажте його знову або виберіть інше')
    return path


def validate_content(text, photo_url=None, text_format='plain', button_text=None, button_url=None):
    plain = visible_text(text, text_format)
    if not plain.strip():
        raise ValueError('Додайте текст повідомлення')
    limit = 1024 if photo_url else 4096
    if len(plain) > limit:
        raise ValueError(f'Повідомлення {"з фото" if photo_url else "без фото"} може містити до {limit} знаків. Зараз: {len(plain)}')
    if photo_url and not local_media_name(photo_url) and not valid_url(photo_url):
        raise ValueError('Зображення: завантажте файл або вкажіть пряме HTTP(S)-посилання')
    if bool(button_text) != bool(button_url):
        raise ValueError('Для кнопки потрібні і текст, і посилання')
    if button_url and not valid_url(button_url, button=True):
        raise ValueError('Посилання кнопки має починатися з https://, http:// або tg://')
    return plain
