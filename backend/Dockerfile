FROM python:3.12-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app PATH=/venv/bin:$PATH
ARG APP_UID=1000
ARG APP_GID=1000
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g "$APP_GID" shop \
    && useradd -u "$APP_UID" -g "$APP_GID" -m -s /usr/sbin/nologin shop
COPY --from=build /venv /venv
COPY . .
RUN chown -R shop:shop /app
USER shop
CMD ["python", "-m", "bot"]
