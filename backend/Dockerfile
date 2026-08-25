FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app

WORKDIR /app

# postgresql-client потрібен планувальнику: бекапи знімає pg_dump, а не
# застосунок. Тримати для цього окремий образ не варто — різниця в кілька
# мегабайтів, зате всі сервіси збираються з одного Dockerfile.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "bot"]
