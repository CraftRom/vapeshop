"""Shared field classification for query strings and structured logs."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_FIELDS = {'password', 'passwordhash', 'passwd', 'pwd', 'token', 'secret',
                 'apikey', 'initdata', 'key', 'sid', 'authorization', 'cookie', 'setcookie', 'csrf'}


def field_name(value):
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


def secret_field(value):
    name = field_name(value)
    return name in SECRET_FIELDS or name.endswith(('password', 'token', 'secret', 'apikey'))


def safe_query_pairs(pairs):
    return [(key, '[REDACTED]' if secret_field(key) or field_name(key) in {'login', 'username'} else value)
            for key, value in pairs]


def redact_url_queries(text):
    def safe(match):
        try:
            url = urlsplit(match.group())
            if not url.query and '@' not in url.netloc:
                return match.group()
            host = '[REDACTED]@' + url.netloc.rsplit('@', 1)[1] if '@' in url.netloc else url.netloc
            query = urlencode(safe_query_pairs(parse_qsl(url.query, keep_blank_values=True)))
            return urlunsplit((url.scheme, host, url.path, query, ''))
        except ValueError:
            return '[REDACTED URL]'
    return re.sub(r'https?://[^\s<>"\']+', safe, text)
