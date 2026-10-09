"""Run security checks against a native nginx >=1.30.5. No VPS or Docker required.
NGINX_BINARY=/absolute/nginx python3 qa/qa-nginx-security.py
"""
import http.client, importlib.util, os, pathlib, socket, ssl, subprocess, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT=pathlib.Path(__file__).resolve().parents[1]
NGINX=os.environ.get('NGINX_BINARY','nginx')
checks=0

def check(ok,label):
 global checks
 checks+=1;print(('PASS' if ok else 'FAIL'),label,flush=True)
 if not ok:raise AssertionError(label)

class Upstream(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path == '/api/health':
   if self.headers.get('Host') not in {'127.0.0.1', 'example.test'}:
    self.send_response(400);self.end_headers();self.wfile.write(b'Invalid host header');return
   self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"ok":true}');return
  data=b'<html><body>QA</body></html>';self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(data)
 def do_POST(self):self.do_GET()
 def log_message(self,*args):pass

with tempfile.TemporaryDirectory(prefix='nginx-security-') as directory:
 p=pathlib.Path(directory)
 for name in ['logs','promo.d','deny.d','hsts.d','cert','media']:(p/name).mkdir()
 upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
 threading.Thread(target=upstream.serve_forever,daemon=True).start()
 port=upstream.server_port
 subprocess.run(['openssl','req','-x509','-nodes','-newkey','rsa:2048','-days','1','-keyout',str(p/'cert/key.pem'),'-out',str(p/'cert/cert.pem'),'-subj','/CN=example.test'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 app=(ROOT/'deploy/nginx/app.conf.template').read_text().replace('__DOMAIN__','example.test')
 app=app.replace('/etc/nginx/',str(p)+'/').replace('/var/log/nginx/',str(p/'logs')+'/')
 app=app.replace('/etc/letsencrypt/live/example.test/fullchain.pem',str(p/'cert/cert.pem')).replace('/etc/letsencrypt/live/example.test/privkey.pem',str(p/'cert/key.pem'))
 app=app.replace('listen 80','listen 127.0.0.1:5080').replace('listen 443','listen 127.0.0.1:5443').replace('listen 127.0.0.1:8080','listen 127.0.0.1:5780')
 app=app.replace('http://api:8000',f'http://127.0.0.1:{port}').replace('http://miniapp:80',f'http://127.0.0.1:{port}').replace('http://dashboard:80',f'http://127.0.0.1:{port}').replace('/data/media/',str(p/'media')+'/')
 (p/'app.conf').write_text(app)
 # Validate the config produced by the isolated promo controller as well.
 spec=importlib.util.spec_from_file_location('promo_controller',ROOT/'deploy/promo-controller/controller.py');controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller)
 promo=controller.https_config('promo.test').replace('/etc/nginx/',str(p)+'/').replace('/data/media/',str(p/'media')+'/')
 promo=promo.replace('/etc/letsencrypt/live/promo.test/fullchain.pem',str(p/'cert/cert.pem')).replace('/etc/letsencrypt/live/promo.test/privkey.pem',str(p/'cert/key.pem'))
 promo=promo.replace('listen 80','listen 127.0.0.1:5080').replace('listen 443','listen 127.0.0.1:5443').replace('http://api:8000',f'http://127.0.0.1:{port}')
 (p/'promo.d/promo.conf').write_text(promo)
 (p/'rates.conf').write_text((ROOT/'deploy/nginx/ratelimit.conf').read_text())
 (p/'nginx.conf').write_text(f'user root root; pid {p}/nginx.pid; error_log {p}/logs/error.log; events {{ worker_connections 256; }} http {{ include {ROOT}/qa/nginx-mime.types; include {p}/rates.conf; include {p}/app.conf; }}')
 command=[NGINX,'-p',str(p)+'/', '-c',str(p/'nginx.conf')]
 syntax=subprocess.run(command+['-t'],capture_output=True,text=True)
 check(syntax.returncode==0,'nginx syntax including dynamic promo config: '+syntax.stderr.strip())
 (p/'media/photo.jpg').write_bytes(b'qa-jpeg')
 (p/'media/unsafe.svg').write_bytes(b'<svg/>')
 (p/'media/link.png').symlink_to('/etc/hosts')
 proc=subprocess.Popen(command+['-g','daemon off; master_process off;'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 context=ssl._create_unverified_context()
 def request(path,host='example.test',secure=True,method='GET'):
  cls=http.client.HTTPSConnection if secure else http.client.HTTPConnection
  args={'context':context} if secure else {}
  c=cls('127.0.0.1',5443 if secure else 5080,timeout=3,**args)
  try:
   c.request(method,path,headers={'Host':host});resp=c.getresponse();resp.read();return resp.status,dict((k.lower(),v) for k,v in resp.getheaders())
  finally:c.close()
 try:
  for i in range(50):
   try:request('/');break
   except OSError:time.sleep(.1)
  status,headers=request('/')
  check(status==200 and '1.30' not in headers.get('server',''),'dashboard served without version disclosure')
  check("frame-ancestors 'none'" in headers['content-security-policy'] and headers['x-frame-options']=='DENY','dashboard clickjacking protection')
  check('unsafe-inline' not in headers['content-security-policy'].split('script-src')[1].split(';')[0],'dashboard scripts exclude unsafe-inline')
  for path in ['/','/app']:
   status,headers=request(path)
   check('permissions-policy' in headers and headers.get('x-permitted-cross-domain-policies')=='none','header inheritance preserved '+path)
  status,headers=request('/app')
  check('https://telegram.org' in headers['content-security-policy'] and 'https://web.telegram.org' in headers['content-security-policy'] and 'x-frame-options' not in headers,'Telegram SDK and embedding preserved')
  status,headers=request('/media/photo.jpg')
  check(status==200 and headers.get('content-type')=='image/jpeg' and headers.get('x-content-type-options')=='nosniff','raster media MIME and nosniff')
  check(request('/media/unsafe.svg')[0]==404,'active media format rejected')
  check(request('/media/link.png')[0] in (403,404),'symlink media rejected')
  check(request('/api/health',secure=False)[0]==301,'plain HTTP redirects before API')
  c=http.client.HTTPConnection('127.0.0.1',5780,timeout=3)
  c.request('GET','/__deploy_api_health');resp=c.getresponse();body=resp.read();c.close()
  check(resp.status==200 and body==b'{"ok":true}','internal nginx health uses an allowed loopback Host')
  check(request('/api/health')[0]==200,'main HTTPS health reaches API with main domain Host')
  check(request('/__deploy_api_health')[1].get('content-type')!='application/json','internal health is not available through public HTTPS')
  for secure in (False,True):
   try:request('/',host='attacker.example',secure=secure);closed=False
   except http.client.RemoteDisconnected:closed=True
   check(closed,'unknown host connection closed '+str(secure))
  request('/api/telegram/SENSITIVE_WEBHOOK/777001?password=PRIVATE_PASSWORD',method='POST')
  time.sleep(.1)
  text=(p/'logs/access.log').read_text()
  check('SENSITIVE_WEBHOOK' not in text and 'PRIVATE_PASSWORD' not in text and '[REDACTED]' in text,'access logs omit webhook path secret and query values')
  codes=[request('/api/auth/browser-login',method='POST')[0] for _ in range(8)]
  check(429 in codes,'browser login gets dedicated rate limit')
  check(request('/',host='promo.test')[0]==200,'dynamic promo domain remains accessible')
  print(f'NGINX SECURITY: {checks}/{checks}',flush=True)
 finally:
  proc.terminate();proc.wait(timeout=5);upstream.shutdown()
