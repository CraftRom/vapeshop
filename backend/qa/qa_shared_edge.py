"""ELFAR і ACCORD NICHE на одному сервері: контракт спільного nginx.

ACCORD (/opt/accord-niche/scripts/connect_elfar_edge.py) підключається до
nginx цього проєкту. Перевіряємо, що файли репозиторію вже містять рівно те,
що вписує його інсталятор, і що деплой ELFAR захищає обидва проєкти.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
read = lambda p: (ROOT / p).read_text(encoding="utf-8")
checks = []
check = lambda ok, label: checks.append((label, bool(ok))) or print(("  ✓ " if ok else "  ✗ ") + label)

compose = read("deploy/docker-compose.prod.yml")
deploy = read("deploy/deploy.sh")
edge = read("deploy/shared-edge.sh")
unit = read("deploy/elfar.service")

# The same regexes and strings the ACCORD installer uses (patch_compose).
MOUNT = "./nginx/accord-main.conf:/etc/nginx/conf.d/20-accord.conf:ro"
nginx = re.search(r"^  nginx:\n.*?(?=^  [A-Za-z0-9_-]+:|^\S|\Z)", compose, re.M | re.S)
block = nginx[0] if nginx else ""
networks = re.search(r"^networks:\n.*?(?=^\S|\Z)", compose, re.M | re.S)
check(re.search(r"(?m)^name: deploy$", compose), "Compose project ELFAR завжди 'deploy' (deploy-nginx-1 для ACCORD)")
check(MOUNT in block, "nginx монтує конфіг ACCORD тим самим рядком, що й інсталятор ACCORD")
check("    networks: [internal, accord_edge]" in block, "nginx у спільній мережі — інсталятору ACCORD нічого правити")
check(networks and re.search(r"^  accord_edge:\s*\n    external: true\s*\n    name: accord-shared-edge\s*$", networks[0], re.M),
      "мережа accord-shared-edge зовнішня: down ELFAR її не видаляє")
other = [svc for svc, body in re.findall(r"(?ms)^  ([a-z][a-z0-9_-]*):\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|^\S|\Z)", compose.split("\nnetworks:\n")[0])
         if svc != "nginx" and "accord_edge" in body]
check(not other, f"у спільній мережі з боку ELFAR лише nginx {other}")
check(".gitignore" and "deploy/nginx/accord-main.conf" in read(".gitignore"), "конфіг ACCORD живе на сервері, не в git")

check("# Managed by ACCORD NICHE shared-edge installer" in edge, "заглушка має позначку, яку приймає інсталятор ACCORD")
reserved = re.search(r'^RESERVED_ALIASES="([^"]*)"', edge, re.M)
for name in ("api", "dashboard", "miniapp"):
    check(reserved and name in reserved[1].split(), f"guard не пускає чужий alias '{name}' у спільну мережу")
check("--pull never" in edge and "--entrypoint nginx nginx -t" in edge, "nginx -t — у тимчасовому контейнері з тими самими mount")

def before(text, first, second, label):
    a, b = text.find(first), text.find(second)
    check(a != -1 and b != -1 and a < b, label)
before(deploy, "shared-edge.sh ensure", 'echo "==> Preflight docker compose"', "deploy: мережа й конфіг ACCORD — до preflight compose")
before(deploy, "shared-edge.sh guard", '"${COMPOSE[@]}" build', "deploy: перевірка чужих контейнерів — до build і restart")
before(deploy, "shared-edge.sh nginx-test", '"${COMPOSE[@]}" up -d --no-deps --force-recreate nginx\n\nnginx_core_ok=0',
       "deploy: nginx -t з конфігом ACCORD — до перестворення nginx")
check("shared-edge.sh verify" in deploy, "deploy показує стан сайтів ACCORD після оновлення")
check('image prune -f --filter "label=com.docker.compose.project=deploy"' in deploy and "image prune -f >" not in deploy,
      "prune прибирає лише образи ELFAR, не ACCORD")
check(not re.search(r"docker (system|volume|network|container) prune", deploy + edge), "жодних глобальних prune")
lock_at = deploy.find("flock -")
check("elfar-accord-edge.lock" in deploy and 0 < lock_at < deploy.find("shared-edge.sh ensure"),
      "deploy тримає той самий замок, що й connect_elfar_edge.py ACCORD, з самого початку")
check("umask 000" in deploy and "exec 9<" in deploy, "замок відкривається на читання: root (ACCORD) і shop (ELFAR) ділять один файл")
check("ExecStartPre=/bin/bash __REPO_DIR__/deploy/shared-edge.sh ensure" in unit, "після ребуту nginx стартує з мережею ACCORD")
check("shared-edge.sh ensure" in read("deploy/certbot-init.sh"), "certbot-init перестворює nginx лише з мережею ACCORD")

failed = [label for label, ok in checks if not ok]
print(f"\nSHARED EDGE: {len(checks) - len(failed)}/{len(checks)}")
raise SystemExit(1 if failed else 0)
