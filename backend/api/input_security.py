"""Unambiguous request parsing; SQL safety remains the repository's bound queries."""
import json
import re
from urllib.parse import parse_qsl


LOGIN_PATHS = {'/api/auth/login', '/api/auth/browser-login'}
PUBLIC_PROMO_PATHS = {'/api/landing-pages/public/render/page', '/api/landing-pages/public/go/button'}


def credentials_body(path: str, method: str) -> bool:
    path = path.rstrip('/')
    return (path in LOGIN_PATHS and method == 'POST') or (
        bool(re.fullmatch(r'/api/operators(?:/[0-9]+)?', path))
        and method in {'POST', 'PUT', 'PATCH'})


def check_url(path: str, query: bytes, method: str) -> None:
    """Every current non-promo API query field is scalar, never last-value-wins."""
    path.encode('utf-8')
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise ValueError('Некоректний шлях запиту')
    if not path.startswith('/api/'):
        return
    if len(query) > 8192:
        raise ValueError('Адреса запиту надто довга')
    if query and (path.rstrip('/') in LOGIN_PATHS or credentials_body(path, method)):
        raise ValueError('Облікові дані передаються лише в JSON-тілі запиту, без параметрів URL')
    if path in PUBLIC_PROMO_PATHS:
        return
    try:
        raw = query.decode('ascii')
        if re.search(r'%(?![0-9A-Fa-f]{2})', raw):
            raise ValueError()
        pairs = parse_qsl(raw, keep_blank_values=True, encoding='utf-8',
                          errors='strict', max_num_fields=100)
    except (UnicodeError, ValueError):
        raise ValueError('Некоректне кодування або кількість параметрів URL') from None
    seen = set()
    for key, value in pairs:
        if key in seen:
            raise ValueError('Параметри URL не можуть повторюватися')
        if any(ord(char) < 32 or ord(char) == 127 for char in key + value):
            raise ValueError('Керівні символи в параметрах URL заборонені')
        seen.add(key)


def check_credentials_json(body: bytes) -> None:
    def distinct_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Повторення JSON-полів заборонено')
            result[key] = value
        return result

    def no_constant(value):
        raise ValueError('Некоректна JSON-константа')

    def unicode_strings(value):
        if isinstance(value, str):
            value.encode('utf-8')  # reject lone surrogates, preserve real Unicode verbatim
        elif isinstance(value, dict):
            for key, item in value.items():
                unicode_strings(key)
                unicode_strings(item)
        elif isinstance(value, list):
            for item in value:
                unicode_strings(item)

    try:
        value = json.loads(body.decode('utf-8'), object_pairs_hook=distinct_object,
                           parse_constant=no_constant)
        if not isinstance(value, dict):
            raise ValueError()
        unicode_strings(value)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('Потрібен коректний JSON-об’єкт без повторених полів') from None
