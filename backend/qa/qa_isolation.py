"""F16: separate process databases and narrowly scoped cleanup."""
import json, os, subprocess, sys, unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from qa_paths import qa_db_path
ROOT=Path(__file__).resolve().parents[1]
CODE='''import json, os
from pathlib import Path
from qa_paths import qa_db_path,qa_db_url
p=qa_db_path("same.db");Path(p).write_text("owned")
print(json.dumps({"path":p,"url":qa_db_url("same.db"),"sentinel":Path(os.environ["SENTINEL"]).read_text()}))
'''
class IsolationTests(unittest.TestCase):
 def test_two_simultaneous_suites_get_different_paths(self):
  with TemporaryDirectory() as folder:
   sentinel=Path(folder)/'production.db';sentinel.write_text('DO NOT DELETE')
   env=dict(os.environ,SENTINEL=str(sentinel),PYTHONPATH=str(ROOT),DATABASE_URL='postgresql+asyncpg://production.invalid/shop')
   env.pop('QA_DATA_DIR',None)
   children=[subprocess.Popen([sys.executable,'-c',CODE],stdout=subprocess.PIPE,text=True,env=env) for _ in range(2)]
   data=[json.loads(c.communicate(timeout=15)[0]) for c in children]
   self.assertTrue(all(c.returncode==0 for c in children));self.assertNotEqual(data[0]['path'],data[1]['path'])
   self.assertTrue(all(x['url'].startswith('sqlite+aiosqlite:///') for x in data))
   self.assertEqual(sentinel.read_text(),'DO NOT DELETE')
   self.assertTrue(all(not Path(x['path']).exists() for x in data))
 def test_filenames_cannot_escape_directory(self):
  for name in ['../production.db','/tmp/production.db','production.sql']:
   with self.assertRaises(ValueError):qa_db_path(name)
 def test_runner_has_no_shared_database_deletion(self):
  runner=(ROOT/'qa/run_all.sh').read_text()
  self.assertNotIn('rm -f /tmp/qa_',runner);self.assertIn('mktemp -d',runner)
 def test_no_fixed_tmp_db_paths_remain(self):
  import re
  files=[*(ROOT/'qa').glob('*.py'),*ROOT.glob('tests*.py')]
  for f in files:
   if f.name==Path(__file__).name:continue
   self.assertFalse(re.search(r'/tmp/[\w-]+\.db',f.read_text()),f.name)
if __name__=='__main__':unittest.main(verbosity=2)
