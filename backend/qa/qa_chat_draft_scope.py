"""Real HTTP cookie-session profiles provide stable, non-authorizing draft scopes."""
from qa_paths import qa_db_path
from qa_common import boot, Report
app, Session, fake = boot(qa_db_path('chat_draft_scope.db'))
from fastapi.testclient import TestClient
from api.browser_sessions import profile
from api.auth import Principal
from shop.entities import OperatorRole
from shop.config import settings
from unittest.mock import patch
r = Report('CHAT DRAFT SCOPE')
headers = {'X-Dashboard-Request': '1', 'Origin': settings.public_url}
admin = TestClient(app, base_url='https://testserver')
login = admin.post('/api/auth/browser-login', json={'login':'admin','password':'secret'}, headers=headers)
r.check(login.status_code == 200, 'owner browser login succeeds')
a = login.json()
r.check(len(a['draft_scope']) == 64 and a['draft_scope'] != a['csrf_token'] and 'access_token' not in a,
        'draft scope is opaque and separate from credentials')
r.check(admin.get('/api/auth/session').json()['draft_scope'] == a['draft_scope'], 'reload keeps same scope')
again = admin.post('/api/auth/browser-login', json={'login':'admin','password':'secret'}, headers=headers).json()
r.check(again['draft_scope'] == a['draft_scope'] and again['csrf_token'] != a['csrf_token'],
        'scope remains stable while browser session and CSRF rotate')
anonymous = TestClient(app, base_url='https://testserver')
r.check(anonymous.get('/api/orders', headers={'Authorization':'Bearer '+a['draft_scope']}).status_code == 401,
        'draft scope grants no API access')
r.check(anonymous.get('/api/auth/session').status_code == 401, 'anonymous session exposes no scope')
protected = {**headers, 'X-CSRF-Token': again['csrf_token']}
operators = []
for login_name in ('draft-a','draft-b'):
    created = admin.post('/api/operators', json={'login':login_name,'name':'Same Name','password':'StrongQa!2026'}, headers=protected)
    assert created.status_code == 201, created.text
    operators.append(created.json())
clients = [TestClient(app, base_url='https://testserver') for _ in operators]
profiles = [client.post('/api/auth/browser-login', json={'login':operator['login'],'password':'StrongQa!2026'},headers=headers).json()
            for client, operator in zip(clients, operators)]
r.check(profiles[0]['name'] == profiles[1]['name'] and profiles[0]['draft_scope'] != profiles[1]['draft_scope'],
        'managers with same display name have different draft scopes')
r.check(a['draft_scope'] not in {p['draft_scope'] for p in profiles}, 'owner and manager scopes are isolated')
change = admin.put('/api/operators/'+str(operators[0]['id']), json={'password':'ChangedQa!2026'},headers=protected)
r.check(change.status_code == 200 and clients[0].get('/api/auth/session').status_code == 401, 'password change revokes old cookie')
new = clients[0].post('/api/auth/browser-login', json={'login':'draft-a','password':'ChangedQa!2026'},headers=headers).json()
r.check(new['draft_scope'] != profiles[0]['draft_scope'], 'password change rotates draft scope')
p = Principal('test','Old Name',OperatorRole.MANAGER,999,3)
base = profile(p,'csrf-one')['draft_scope']
r.check(profile(Principal('test','New Name',p.role,999,3),'csrf-two')['draft_scope'] == base, 'display name and CSRF are not account identity')
r.check(profile(Principal('test','Old Name',OperatorRole.ADMIN,999,3),'csrf')['draft_scope'] != base, 'role change rotates draft scope')
with patch.object(settings,'jwt_secret','other-secret-key-at-least-32-characters'):
    r.check(profile(p,'csrf')['draft_scope'] != base, 'another installation secret has different scope')
with patch.object(settings,'dashboard_password','changed-owner-password'):
    owner = Principal(settings.dashboard_login,'Owner',OperatorRole.SYSADMIN,0)
    r.check(profile(owner,'csrf')['draft_scope'] != a['draft_scope'], 'owner password change rotates draft scope')
logout = clients[0].post('/api/auth/logout',headers={**headers,'X-CSRF-Token':new['csrf_token']})
r.check(logout.status_code == 204 and clients[0].get('/api/auth/session').status_code == 401, 'logout revokes browser session normally')
for client in [admin,anonymous,*clients]: client.close()
raise SystemExit(bool(r.done()))
