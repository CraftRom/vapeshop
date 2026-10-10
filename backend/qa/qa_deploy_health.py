"""Run the real phased deploy with a simulated Docker daemon and Host-aware probes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DOCKER = '''#!/usr/bin/env python3
import json, os, sys
a=sys.argv[1:]
with open(os.environ['QA_DOCKER_CALLS'],'a') as f: f.write(json.dumps(a)+'\\n')
if a[0]=='inspect':
 fmt=a[a.index('-f')+1]
 print('healthy' if '.State.Health' in fmt else 'true' if '.State.Running' in fmt else 'deploy-api:latest' if '.Config.Image' in fmt else 'sha256:qa')
elif a[0]=='compose':
 cmd=a[5]; args=a[6:]
 if cmd=='ps' and '-q' in args: print('qa-'+args[-1])
 elif cmd=='run' and 'shop.catalog_upgrade' in args: print('0')
 elif cmd=='exec' and 'wget' in args:
  if 'http://127.0.0.1:8080/__deploy_api_health' in args:
   sys.exit(22 if os.environ.get('QA_FAIL_INTERNAL')=='1' else 0)
  if 'https://127.0.0.1/api/health' in args:
   good='--header=Host: '+os.environ['QA_EXPECTED_DOMAIN'] in args and '--no-check-certificate' in args
   sys.exit(22 if not good or os.environ.get('QA_FAIL_TLS')=='1' else 0)
  sys.exit(22) # old Host: api and HTTP redirect probes are deliberately rejected
'''


class DeployHealth(unittest.TestCase):
    def deploy(self, domain='shop.example.com', **failures):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'deploy/nginx/generated').mkdir(parents=True)
            (root/'backend/shop').mkdir(parents=True)
            (root/'bin').mkdir()
            shutil.copy(ROOT/'deploy/deploy.sh',root/'deploy/deploy.sh')
            shutil.copy(ROOT/'deploy/domain_config.py',root/'deploy/domain_config.py')
            (root/'deploy/check-public-routes.py').write_text("import os,sys\nsys.exit(1 if os.environ.get('QA_FAIL_PUBLIC') == '1' else 0)\n")
            shutil.copy(ROOT/'backend/shop/production_security.py',root/'backend/shop/production_security.py')
            for name in ['backup.sh','render-nginx.sh']:
                script=root/'deploy'/name;script.write_text('#!/bin/sh\nexit 0\n');script.chmod(0o700)
            (root/'deploy/nginx/generated/app.conf').write_text('# simulated previous nginx config\n')
            values={'PUBLIC_URL':'https://'+domain,'BOT_TOKEN':'777001:TESTTOKEN','JWT_SECRET':'x'*32,
                    'DATA_ENCRYPTION_KEY':'unused-host-preflight','DASHBOARD_PASSWORD':'Valid-password-2026',
                    'POSTGRES_USER':'shop','POSTGRES_PASSWORD':'postgres-secret','POSTGRES_DB':'shop',
                    'REDIS_PASSWORD':'redis-secret','REDIS_URL':'redis://:redis-secret@redis:6379/0',
                    'PROMO_CONTROLLER_TOKEN':'valid-test-controller-token'}
            (root/'.env').write_text('\n'.join(f'{k}={v}' for k,v in values.items()))
            docker=root/'bin/docker';docker.write_text(DOCKER);docker.chmod(0o700)
            sleep=root/'bin/sleep';sleep.write_text('#!/bin/sh\nexit 0\n');sleep.chmod(0o700)
            calls=root/'docker-calls'
            env={**os.environ,**failures,'PATH':str(root/'bin')+':'+os.environ['PATH'],
                 'QA_DOCKER_CALLS':str(calls),'QA_EXPECTED_DOMAIN':'elfar.pp.ua' if domain=='www.elfar.pp.ua' else domain}
            result=subprocess.run(['bash',str(root/'deploy/deploy.sh')],env=env,text=True,capture_output=True,timeout=15)
            return result,[json.loads(line) for line in calls.read_text().splitlines()]

    def test_healthy_nginx_reaches_phase_six_without_rollback(self):
        result,calls=self.deploy()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Фінальний API health: OK',result.stdout)
        self.assertNotIn('Rollback CORE runtime',result.stderr)
        probes=[a for a in calls if 'wget' in a]
        self.assertTrue(any('http://127.0.0.1:8080/__deploy_api_health' in a for a in probes))
        self.assertTrue(any('https://127.0.0.1/api/health' in a for a in probes))
        self.assertFalse(any('http://api:8000/api/health' in a for a in probes))

    def test_legacy_www_uses_same_domain_as_render_nginx(self):
        result,calls=self.deploy('www.elfar.pp.ua')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(any('--header=Host: elfar.pp.ua' in a for a in calls))

    def test_broken_internal_route_still_triggers_rollback(self):
        result,calls=self.deploy(QA_FAIL_INTERNAL='1')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Rollback CORE runtime',result.stderr)
        self.assertNotIn('ФАЗА 6/6',result.stdout)
        self.assertTrue(any('-S' in a and 'http://127.0.0.1:8080/__deploy_api_health' in a for a in calls))

    def test_broken_tls_route_still_triggers_rollback(self):
        result,calls=self.deploy(QA_FAIL_TLS='1')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Основний nginx route',result.stderr)
        self.assertIn('Rollback CORE runtime',result.stderr)
        self.assertNotIn('ФАЗА 6/6',result.stdout)

    def test_broken_legacy_or_storefront_route_triggers_rollback(self):
        result,calls=self.deploy(QA_FAIL_PUBLIC='1')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Rollback CORE runtime',result.stderr)
        self.assertNotIn('ФАЗА 6/6',result.stdout)

    def test_real_api_reproduces_old_host_failure_and_accepts_probe_host(self):
        os.environ['TRUSTED_HOSTS']=''
        from qa_common import boot
        from fastapi.testclient import TestClient
        app,_,_=boot('/tmp/qa_deploy_health.db')
        client=TestClient(app)
        self.assertEqual(client.get('/api/health',headers={'Host':'api:8000'}).status_code,400)
        self.assertEqual(client.get('/api/health',headers={'Host':'127.0.0.1'}).status_code,200)
        self.assertEqual(client.get('/api/health',headers={'Host':'elfar.pp.ua'}).status_code,200)
        self.assertEqual(client.get('/api/health',headers={'Host':'attacker.example'}).status_code,400)


if __name__=='__main__':
    unittest.main(verbosity=2)
