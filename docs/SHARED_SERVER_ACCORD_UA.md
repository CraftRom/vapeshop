# ELFAR і ACCORD NICHE на одному сервері

Обидва магазини працюють на одному VPS, в одному Docker:

| | ELFAR (цей репозиторій) | ACCORD NICHE |
|---|---|---|
| Каталог | `/opt/elfar` | `/opt/accord-niche` |
| Compose project | `deploy` (зафіксовано `name: deploy`) | `accord-niche` (`COMPOSE_PROJECT_NAME` у `.env.domains`) |
| Публічні порти | `80`, `443` — nginx ELFAR | лише `127.0.0.1:18081–18083` |
| База, Redis, API | свої, у мережі `deploy_internal` | свої, у своїй мережі |

**Спільний лише один вузол — nginx ELFAR (`deploy-nginx-1`).** Він приймає HTTPS для обох проєктів:

- мережа `accord-shared-edge` (зовнішня). З боку ELFAR до неї підключений лише nginx, з боку ACCORD — лише `accord-website`, `accord-miniapp`, `accord-dashboard`;
- файл `deploy/nginx/accord-main.conf` монтується як `conf.d/20-accord.conf`. Його пише інсталятор ACCORD, у git цього репозиторію файла немає;
- сертифікати ACCORD лежать у спільному томі certbot. Їх подовжує той самий renew-цикл promo-controller.

Обидва підключення записані в `deploy/docker-compose.prod.yml` рівно в тому вигляді, який вписує `connect_elfar_edge.py`. Тому оновлення ELFAR їх більше не стирає, а інсталятор ACCORD нічого в цьому файлі не змінює.

## Що робить деплой ELFAR (`deploy/shared-edge.sh`)

1. **ensure.** Створює мережу `accord-shared-edge` і заглушку `accord-main.conf` з позначкою інсталятора ACCORD, якщо їх ще немає. Чужий файл без позначки зупиняє деплой. Той самий крок виконують `elfar.service` перед стартом після перезавантаження і `certbot-init.sh`.
2. **guard.** Виконується до збірки та перезапуску:
   - у project `deploy` не повинно бути контейнерів з іншого каталогу. Інакше ELFAR перестворив би або прибрав би чужий стек;
   - у спільній мережі жоден контейнер ACCORD не повинен мати імені сервісу ELFAR (`api`, `dashboard`, `miniapp` тощо). Інакше Docker DNS віддав би nginx ELFAR чужу адресу.
3. **nginx-test.** Перед перестворенням nginx запускається `nginx -t` у тимчасовому контейнері з тими самими mount. Битий конфіг або зниклий сертифікат ACCORD зупиняє деплой ще до того, як зачепить робочий nginx, а отже й ELFAR.
4. **verify.** Після перестворення перевіряється, що nginx у спільній мережі й домени ACCORD відповідають. Збій ACCORD виводиться як попередження, ELFAR через нього не відкочується.
5. `docker image prune` прибирає лише образи з міткою `com.docker.compose.project=deploy`. Образи, томи й мережі ACCORD деплой ELFAR не чіпає.

`docker compose down` ELFAR (зокрема при вимкненні сервера) не видаляє зовнішню мережу й не зупиняє ACCORD.

## Перший раз після цієї версії

На VPS `deploy/docker-compose.prod.yml` раніше змінив інсталятор ACCORD. У новій версії репозиторію ті самі зміни вже є, тому локальну правку можна відкинути. Від користувача, що оновлює ELFAR:

```bash
cd /opt/elfar
cp deploy/docker-compose.prod.yml ~/docker-compose.prod.yml.before-1.86.2   # про всяк випадок
git checkout -- deploy/docker-compose.prod.yml   # якщо оновлюєте через git
git pull
bash deploy/deploy.sh
```

Якщо оновлюєте архівом, просто замініть файли: `deploy/nginx/accord-main.conf` в архіві немає, тож його не буде перезаписано. Після деплою:

```bash
docker network inspect accord-shared-edge -f '{{range .Containers}}{{.Name}} {{end}}'
curl -I https://elfar.pp.ua/ && curl -I https://accordniche.pp.ua/
```

## Порядок оновлень

- **ELFAR:** `bash deploy/deploy.sh`. Його перевірки описано вище.
- **ACCORD:** `bash deploy/domains.sh --docker-edge up -d --build` у `/opt/accord-niche`. Сертифікати або домени ACCORD змінює лише `python3 scripts/connect_elfar_edge.py`. Він перестворює тільки `nginx` і `promo-controller` ELFAR з `--no-deps --no-build`.
- Деплой ELFAR і `connect_elfar_edge.py` ACCORD беруть один замок `/run/lock/elfar-accord-edge.lock`. Якщо одночасно запустити обидва, другий чекає до 15 хвилин і не перестворює nginx паралельно.
- У ACCORD legacy-сценарії `deploy/deploy.sh`, `bootstrap.sh`, `certbot-init.sh` та інші старі сценарії відмовляються працювати на сервері з ELFAR (код 3). `COMPOSE_PROJECT_NAME=deploy` або `elfar` у `.env.domains` теж відхиляється: ці імена належать ELFAR.
- Не виконуйте `docker system prune`, `docker volume prune` чи `docker network prune` на цьому сервері. Вони зачеплять обидва проєкти.
