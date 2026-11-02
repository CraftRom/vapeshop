"""Real HTTP/SQLite attacks and SQL binding evidence; never touches a live service."""
import ast
import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql
from qa_common import boot, Report

app, Session, fake = boot('qa_injection_boundaries.db')
from shop.services import login_guard
from shop.repo.sql import SqlRepository
from shop.models import Operator
from shop.db import engine
from shop.logging_setup import redact
from api.request_log import safe_query
from starlette.requests import Request

r = Report('INJECTION BOUNDARIES')
c = TestClient(app)
credentials = {'login': 'admin', 'password': 'secret'}
owner = c.post('/api/auth/login', json=credentials)
r.check(owner.status_code == 200, 'ordinary login still succeeds')
A = {'Authorization': 'Bearer ' + owner.json()['access_token']}
wire = []
def capture(conn, cursor, statement, parameters, context, executemany):
    wire.append((statement, parameters))
event.listen(Session.kw['bind'].sync_engine, 'before_cursor_execute', capture)

for payload in ["' OR 1=1 --", "admin'--", "'; DROP TABLE operators;--", '<script>alert(1)</script>', '%27%20OR%201=1--', "a' UNION SELECT 1--"]:
    login_guard.reset()
    wire.clear()
    response = c.post('/api/auth/login', json={'login': payload, 'password': 'incorrect'})
    bound = [(statement, values) for statement, values in wire if 'operators' in statement.lower()]
    r.check(response.status_code == 401 and 'access_token' not in response.text, 'injected login never authenticates: ' + payload)
    r.check(bound and all(payload not in statement for statement, values in bound)
            and any(payload in values for statement, values in bound), 'injected login stays a driver-bound SQL value')
    response = c.post('/api/auth/login', json={'login': 'admin', 'password': payload})
    r.check(response.status_code == 401, 'SQL/script password cannot bypass verification')

for path in ['/api/auth/login', '/api/auth/browser-login']:
    query = urlencode({'login': 'admin', 'password': 'PRIVATE_URL_SECRET'})
    response = c.post(path + '?' + query, json=credentials, headers={'X-Dashboard-Request': '1'})
    r.check(response.status_code == 400 and 'set-cookie' not in response.headers
            and 'PRIVATE_URL_SECRET' not in response.text, 'login never consumes or reflects URL credentials: ' + path)
    r.check(c.get(path + '?' + query).status_code == 400, 'address-bar GET cannot authenticate: ' + path)

for raw in [b'{"login":"bad","login":"admin","password":"secret"}',
            b'{"login":"bad","log\\u0069n":"admin","password":"secret"}',
            b'{"login":"admin","password":"bad","password":"secret"}',
            b'{"login":"admin","password":NaN}',
            b'{"login":"admin","password":"\\ud800"}', b'[]']:
    response = c.post('/api/auth/login', content=raw, headers={'Content-Type': 'application/json'})
    r.check(response.status_code == 400 and 'access_token' not in response.text, 'malformed or ambiguous credential JSON rejected')
for data in [{**credentials, 'role': 'sysadmin'}, {**credentials, 'operator_id': 0},
             {**credentials, 'password_hash': 'replacement'}, {**credentials, 'login': {'$ne': None}},
             {**credentials, 'password': ['secret']}, {**credentials, 'login': 'admin\x00'}]:
    response = c.post('/api/auth/login', json=data)
    r.check(response.status_code == 422 and 'secret' not in response.text, 'unexpected credential fields/types rejected without echoing password')
r.check(c.post('/api/auth/login', data=credentials).status_code == 415, 'form credentials cannot fall back to an alternate parser')
r.check(c.post('/api/auth/login', content=b'x' * 17000, headers={'Content-Type': 'application/json'}).status_code == 413, 'credential body has a small bounded budget')

literal_password = '  <script>safe-as-password();</script> Україна!  '
operator_data = {'login': 'literal-op', 'name': '<img src=x onerror=alert(1)>', 'password': literal_password}
created = c.post('/api/operators', json=operator_data, headers=A)
r.check(created.status_code == 201 and 'password' not in created.json(), 'operator stores a hash and returns no password')
oid = created.json()['id']
login_guard.reset()
manager_login = c.post('/api/auth/login', json={'login': 'literal-op', 'password': literal_password})
r.check(manager_login.status_code == 200, 'Unicode, whitespace, quotes and script-like password remain literal valid data')
M = {'Authorization': 'Bearer ' + manager_login.json()['access_token']}
r.check(c.post('/api/auth/login', json={'login': 'literal-op', 'password': literal_password.strip()}).status_code == 401, 'password is never silently stripped or rewritten')
r.check(c.put(f'/api/operators/{oid}', json={'password': 'Replacement!2026'}, headers=M).status_code == 403, 'manager cannot change passwords using direct API requests')
r.check(c.put(f'/api/operators/{oid}?password=Replacement!2026', json={'password': 'Replacement!2026'}, headers=A).status_code == 400, 'operator password updates reject query-string overrides')
for extra in [{'login': 'hijacked'}, {'password_hash': 'hijacked'}, {'auth_version': 0}]:
    r.check(c.put(f'/api/operators/{oid}', json=extra, headers=A).status_code == 422, 'operator updates reject mass assignment: ' + next(iter(extra)))
r.check(c.put(f'/api/operators/{oid}', content=b'{"role":"manager","role":"admin"}', headers={**A, 'Content-Type': 'application/json'}).status_code == 400, 'repeated operator roles cannot pick another parser interpretation')
r.check(c.post('/api/operators', json={**operator_data, 'login': '<script>alert(1)</script>'}, headers=A).status_code == 422, 'new operator login follows the existing identifier allowlist')
r.check(c.put(f'/api/operators/{oid}', json={'name': 'nul\x00name'}, headers=A).status_code == 422, 'operator NUL names fail before database storage')
r.check(c.post('/api/auth/login', json={'login': 'literal-op', 'password': literal_password}).status_code == 200, 'blocked mutations leave the real password intact')
r.check(c.put(f'/api/operators/{oid}', json={'password': 'ChangedStrong!2026'}, headers=A).status_code == 200, 'authorized password change still succeeds')
r.check(c.get('/api/orders', headers=M).status_code == 401, 'old bearer is revoked after a real password change')
r.check(c.post('/api/auth/login', json={'login': 'literal-op', 'password': 'ChangedStrong!2026'}).status_code == 200, 'only the new exact password authenticates after change')

first = c.post('/api/catalog/products', json={'name': 'Ordinary item', 'price': '10', 'stock': 2}, headers=A)
second = c.post('/api/catalog/products', json={'name': 'Literal article', 'external_sku': 'part%ABC_1', 'price': '20', 'stock': 2}, headers=A)
r.check(first.status_code == second.status_code == 201, 'catalog attack fixtures exist')
for term in ['%', '_']:
    found = c.get('/api/catalog/products', params={'search': term}, headers=A)
    r.check(found.status_code == 200 and [item['id'] for item in found.json()] == [second.json()['id']], 'SKU wildcard is a literal search character: ' + term)
for term in ["' OR 1=1 --", "'; DROP TABLE products; --", '<svg/onload=alert(1)>', '%2527 OR 1=1']:
    wire.clear()
    found = c.get('/api/catalog/products', params={'search': term}, headers=A)
    r.check(found.status_code == 200 and found.json() == [], 'URL search payload is literal data and never broadens results')
    r.check(all(term not in statement for statement, values in wire), 'URL search never enters SQL statement text')
r.check(len(c.get('/api/catalog/products', headers=A).json()) == 2, 'SQL attacks preserve product rows')
for query in ['limit=1&limit=500', 'limit=1&%6cimit=500', 'search=a&search=b', 'category_id=1&category_id=2', 'search=%00', 'search=%0d%0aX-Forged:yes', 'search=%FF', 'search=%ZZ']:
    response = c.get('/api/catalog/products?' + query, headers=A)
    r.check(response.status_code == 400 and response.headers.get('x-content-type-options') == 'nosniff', 'ambiguous/invalid URL rejected safely: ' + query)
for path in ['/api/operators/1%20OR%201=1', '/api/orders/1%3BDELETE', '/api/orders?limit=1%3BDROP', '/api/orders?status=admin%27--']:
    r.check(c.get(path, headers=A).status_code == 422, 'typed IDs/enums/limits cannot be replaced with executable expressions')
anonymous = TestClient(app)
r.check(anonymous.get('/api/operators?login=admin&password=secret').status_code == 401, 'URL credentials do not substitute for authorization')

secrets = {'pass%77ord': 'URL_SECRET_1', 'newPassword': 'URL_SECRET_2', 'user[password]': 'URL_SECRET_3', 'refresh-token': 'URL_SECRET_4', 'login': 'PRIVATE_LOGIN'}
raw_query = '&'.join(key + '=' + value for key, value in secrets.items())
request = Request({'type': 'http', 'query_string': raw_query.encode(), 'headers': []})
masked = safe_query(request)
r.check(all(value not in masked for value in secrets.values()), 'encoded and aliased URL credentials are redacted in request logs')
masked = redact('request failed: https://host.test/path?' + raw_query)
r.check(all(value not in masked for value in secrets.values()), 'exception URLs redact encoded credential names too')
masked = redact({'password': 'DICT_SECRET', 'nested': {'currentPassword': 'OLD_SECRET'}, 'passwordLength': 12})
r.check('DICT_SECRET' not in str(masked) and 'OLD_SECRET' not in str(masked) and masked['passwordLength'] == '12', 'structured logs redact secret fields and keep safe length metadata')
r.check(engine.sync_engine.hide_parameters is True, 'production database engine suppresses bound values in SQL error text')
payload = "'; DROP TABLE operators;--"
compiled = select(Operator).where(Operator.login == payload).compile(dialect=postgresql.dialect())
r.check(payload not in str(compiled) and payload in compiled.params.values(), 'PostgreSQL compilation binds attack strings separately from SQL')

unsafe = []
root = Path(__file__).resolve().parents[1]
for folder in ['api', 'shop']:
    for path in (root / folder).rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        names = {alias.asname or alias.name for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module == 'sqlalchemy'
                 for alias in node.names if alias.name == 'text'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names:
                if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                    unsafe.append(str(path.relative_to(root)) + ':' + str(node.lineno))
r.check(not unsafe, 'runtime sqlalchemy.text calls accept only static SQL literals', unsafe)
event.remove(Session.kw['bind'].sync_engine, 'before_cursor_execute', capture)
asyncio.run(Session.kw['bind'].dispose())
raise SystemExit(bool(r.done()))
