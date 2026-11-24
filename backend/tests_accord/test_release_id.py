"""A13: the image step and the host check compute the same release IDs."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_check', ROOT / 'scripts/release_check.py')
check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)


def test_image_build_step_writes_the_id_the_host_check_expects(tmp_path):
    copy = tmp_path / 'app'
    shutil.copytree(ROOT / 'backend', copy, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'release.json', '.pytest_cache'))
    written = subprocess.run([sys.executable, '-m', 'shop.build', '--write'], cwd=copy, capture_output=True, text=True,
                             env={'PYTHONPATH': str(copy), 'PATH': '/usr/bin:/bin'}, timeout=60)
    assert written.returncode == 0, written.stderr
    data = json.loads((copy / 'shop/release.json').read_text())
    assert data['built_at'] and len(data['digest']) == 64
    assert written.stdout.strip() == check.expected()['api']
    again = subprocess.run([sys.executable, '-m', 'shop.build'], cwd=copy, capture_output=True, text=True,
                           env={'PYTHONPATH': str(copy), 'PATH': '/usr/bin:/bin'}, timeout=60)
    assert again.stdout.strip() == written.stdout.strip(), 'the running process reports the baked ID'


@pytest.mark.parametrize('app', ['miniapp', 'dashboard'])
def test_python_frontend_digest_matches_the_vite_release_file(app):
    built = ROOT / app / 'dist/release.json'
    if not built.exists():
        pytest.skip('dist не зібрано')
    data = json.loads(built.read_text())
    if data['digest'] != check.frontend_digest(ROOT / app):
        pytest.skip('dist зібрано зі старіших вихідних кодів')
    assert data['id'] == check.expected()[app]


def test_frontend_digest_changes_with_sources_only(tmp_path):
    app = tmp_path / 'site'
    (app / 'src').mkdir(parents=True)
    for name, body in (('index.html', '<html>'), ('package-lock.json', '{}'), ('vite.config.js', 'x'), ('src/a.js', '1')):
        (app / name).write_text(body)
    first = check.frontend_digest(app)
    (app / 'README.md').write_text('docs')
    assert check.frontend_digest(app) == first
    (app / 'src/a.js').write_text('2')
    assert check.frontend_digest(app) != first
