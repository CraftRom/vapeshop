#!/usr/bin/env python3
"""Compare the release this checkout should run with what is actually served (A13).

    python3 scripts/release_check.py            # expected IDs + live check
    python3 scripts/release_check.py --expected # only compute from sources

Expected IDs are computed from the source tree with the same algorithm the
image/Vite builds use. The live check reads the public /release.json of the
dashboard and the Mini App (PUBLIC_URL from .env) and asks the running API
container for its release through deploy/docker-compose.prod.yml.
Read-only: it changes nothing and prints no secrets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
# Served paths: the dashboard lives at the site root, the Mini App under /app/.
FRONTENDS = {"miniapp": "/app/release.json", "dashboard": "/release.json"}


def frontend_digest(app_dir: Path) -> str:
    """Mirror of releaseDigest() in each vite.config.js."""
    files = [p.relative_to(app_dir).as_posix() for p in (app_dir / "src").rglob("*") if p.is_file()]
    files += ["index.html", "package-lock.json", "vite.config.js"]
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode() + b"\0")
        digest.update((app_dir / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def expected() -> dict[str, str]:
    from shop.build import BUILD, source_digest
    ids = {"api": f"{BUILD}+{source_digest(ROOT / 'backend')[:12]}"}
    for app in FRONTENDS:
        ids[app] = f"{app}+{frontend_digest(ROOT / app)[:12]}"
    return ids


def public_url() -> str:
    env = ROOT / ".env"
    for line in env.read_text(encoding="utf-8").splitlines() if env.is_file() else []:
        if line.startswith("PUBLIC_URL="):
            return line.split("=", 1)[1].strip().strip("'\"").rstrip("/")
    raise RuntimeError("PUBLIC_URL не задано в .env")


def live_frontend(path: str) -> str:
    request = urllib.request.Request(public_url() + path,
                                     headers={"User-Agent": "release-check", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return str(json.loads(response.read(4096)).get("id", ""))


def live_api() -> str:
    result = subprocess.run(["docker", "compose", "--env-file", "../.env", "-f", "docker-compose.prod.yml",
                             "exec", "-T", "api", "python", "-m", "shop.build"],
                            cwd=ROOT / "deploy", capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError("контейнер API не відповів")
    return result.stdout.strip().splitlines()[-1]


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument("--expected", action="store_true", help="лише обчислити очікувані ID з вихідних кодів")
    args = cli.parse_args()
    ids = expected()
    if args.expected:
        print(json.dumps(ids, ensure_ascii=False, indent=2))
        return 0
    mismatched = 0
    for component, want in ids.items():
        try:
            got = live_api() if component == "api" else live_frontend(FRONTENDS[component])
        except Exception as exc:  # report and continue with the other components
            got = f"недоступно ({type(exc).__name__})"
        ok = got == want
        mismatched += not ok
        print(f"{'OK ' if ok else 'НІ '} {component:10s} очікується {want}  працює {got}")
    if mismatched:
        print("Частина компонентів працює не з цього коду: перезберіть і перезапустіть їх.")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
