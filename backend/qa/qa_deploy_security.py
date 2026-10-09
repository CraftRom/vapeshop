"""Exercise the real deployment entry point and image/startup guards in isolation."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from shop.production_security import validate_production_security

VALID = {
    "PUBLIC_URL": "https://shop.example.com",
    "BOT_TOKEN": "777001:TESTTOKEN",
    "JWT_SECRET": "x" * 32,
    "DATA_ENCRYPTION_KEY": "unused-host-preflight",
    "DASHBOARD_PASSWORD": "Valid-password-2026",
    "POSTGRES_USER": "shop", "POSTGRES_PASSWORD": "postgres-secret", "POSTGRES_DB": "shop",
    "REDIS_PASSWORD": "redis-secret", "REDIS_URL": "redis://:redis-secret@redis:6379/0",
}


class DeploySecurity(unittest.TestCase):
    def deploy(self, **changes):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "deploy").mkdir()
            (root / "backend/shop").mkdir(parents=True)
            (root / "bin").mkdir()
            shutil.copy(ROOT / "deploy/deploy.sh", root / "deploy/deploy.sh")
            shutil.copy(ROOT / "backend/shop/production_security.py", root / "backend/shop/production_security.py")
            (root / ".env").write_text("\n".join(f"{k}={v}" for k, v in {**VALID, **changes}.items()))
            calls = root / "docker-calls"
            docker = root / "bin/docker"
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$QA_DOCKER_CALLS"\nexit 91\n')
            docker.chmod(0o700)
            env = {**os.environ, "PATH": str(root / "bin") + ":" + os.environ["PATH"], "QA_DOCKER_CALLS": str(calls)}
            result = subprocess.run(["bash", str(root / "deploy/deploy.sh")], env=env, text=True, capture_output=True, timeout=15)
            return result, calls.read_text() if calls.exists() else ""

    def test_bad_password_stops_before_any_docker_call(self):
        for password in ("secret", "a" * 11, "Change-this-password-2026", "your_password_2026"):
            with self.subTest(password_length=len(password)):
                result, calls = self.deploy(DASHBOARD_PASSWORD=password)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DASHBOARD_PASSWORD", result.stderr)
                self.assertIn("12 символів", result.stderr)
                self.assertNotIn(password, result.stderr)
                self.assertEqual(calls, "")
                self.assertNotIn("ФАЗА 2", result.stdout)

    def test_bad_jwt_stops_before_any_docker_call(self):
        result, calls = self.deploy(JWT_SECRET="q" * 31)
        self.assertIn("JWT_SECRET", result.stderr)
        self.assertNotIn("q" * 31, result.stderr)
        self.assertEqual(calls, "")

    def test_minimum_valid_secrets_reach_compose_validation(self):
        result, calls = self.deploy(DASHBOARD_PASSWORD="a" * 12)
        self.assertEqual(result.returncode, 91)  # mock Docker intentionally ends the run
        self.assertIn("env preflight: OK", result.stdout)
        self.assertIn("config --quiet", calls)
        self.assertNotIn("build", calls)

    def test_quoted_password_is_checked_after_normalization(self):
        result, calls = self.deploy(DASHBOARD_PASSWORD='"short"')
        self.assertIn("DASHBOARD_PASSWORD", result.stderr)
        self.assertEqual(calls, "")

    def test_local_http_development_remains_available(self):
        validate_production_security("http://localhost:8000", "local", "local")

    def test_report_uses_same_secret_requirements(self):
        from shop.config import Settings
        s = Settings(_env_file=None, jwt_secret="x" * 31, dashboard_password="secret")
        items = {i["key"]: i for i in s.environment_report()}
        self.assertFalse(items["JWT_SECRET"]["ok"])
        self.assertFalse(items["DASHBOARD_PASSWORD"]["ok"])

    def test_image_preflight_checks_effective_env_before_import(self):
        env = {k: v for k, v in os.environ.items() if k.upper() not in {"PUBLIC_URL", "JWT_SECRET", "DASHBOARD_PASSWORD"}}
        env.update(VALID, DASHBOARD_PASSWORD="image-short", PYTHONPATH=str(ROOT / "backend"))
        result = subprocess.run([sys.executable, "-m", "shop.preflight"], cwd=tempfile.gettempdir(), env=env, text=True, capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DASHBOARD_PASSWORD", result.stderr)
        self.assertNotIn("image-short", result.stderr)
        self.assertNotIn("backend pre-start smoke: OK", result.stdout)

    def test_valid_image_preflight_needs_no_running_database(self):
        from cryptography.fernet import Fernet
        env = {**os.environ, **VALID, "DATA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
               "DATABASE_URL": "sqlite+aiosqlite:////tmp/not-opened-preflight.db", "CORS_ORIGINS": "https://shop.example.com",
               "TRUSTED_HOSTS": "shop.example.com,localhost,127.0.0.1", "PYTHONPATH": str(ROOT / "backend")}
        result = subprocess.run([sys.executable, "-m", "shop.preflight"], cwd=tempfile.gettempdir(), env=env, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("backend pre-start smoke: OK", result.stdout)

    def test_api_lifespan_rejects_before_database_access(self):
        from shop.config import settings
        from api.main import app, lifespan
        from unittest.mock import AsyncMock, patch
        with patch.object(settings, "public_url", VALID["PUBLIC_URL"]), patch.object(settings, "jwt_secret", VALID["JWT_SECRET"]), patch.object(settings, "dashboard_password", "short"), patch("api.main.check_db", new_callable=AsyncMock) as check_db:
            async def start():
                with self.assertRaisesRegex(RuntimeError, "DASHBOARD_PASSWORD"):
                    async with lifespan(app):
                        self.fail("unsafe startup was allowed")
            asyncio.run(start())
            check_db.assert_not_awaited()


if __name__ == "__main__":
    unittest.main(verbosity=2)
