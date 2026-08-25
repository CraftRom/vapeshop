FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app

# UID/GID користувача, від якого працюють процеси. Передаються збіркою, щоб
# збігатися з користувачем shop на хості: інакше файли, які контейнер пише
# у примонтований каталог backups, належали б чужому UID, і власник сервера
# не зміг би ні прочитати їх, ні видалити без sudo.
ARG APP_UID=1000
ARG APP_GID=1000

WORKDIR /app

# postgresql-client потрібен планувальнику: бекапи знімає pg_dump, а не
# застосунок. Тримати для цього окремий образ не варто — різниця в кілька
# мегабайтів, зате всі сервіси збираються з одного Dockerfile.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Залежності ставимо ще від root — у /usr/local, куди застосунку писати
# не потрібно й не можна.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd -g "$APP_GID" shop \
    && useradd -u "$APP_UID" -g "$APP_GID" -m -s /usr/sbin/nologin shop

COPY . .
RUN chown -R shop:shop /app

# Далі — без root. Якщо колись знайдуть діру в залежності, зловмисник
# отримає права звичайного користувача всередині контейнера, а не root,
# який ще й збігається з root на хості при монтуванні томів.
USER shop

CMD ["python", "-m", "bot"]
