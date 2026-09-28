# syntax=docker/dockerfile:1
# ---------------------------------------------------------------- 1) Frontend bauen
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- 2) Python-Abhängigkeiten
FROM python:3.12-slim-bookworm AS pydeps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r /tmp/requirements.txt

# ---------------------------------------------------------------- 3) Laufzeit
FROM python:3.12-slim-bookworm AS runtime
ARG VERSION=1.0.0
LABEL org.opencontainers.image.title="FitForge" org.opencontainers.image.version=$VERSION

# pg_dump 16 (passend zu PostgreSQL 16) aus dem offiziellen PGDG-Repo, tzdata für TZ
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg tzdata \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PUID=1000 PGID=1000 TZ=Europe/Berlin \
    DATA_DIR=/data FRONTEND_DIR=/app/frontend

RUN groupadd -g 1000 fitforge && useradd -u 1000 -g fitforge -d /app -s /usr/sbin/nologin fitforge
COPY --from=pydeps /opt/venv /opt/venv
WORKDIR /app/backend
COPY backend/ /app/backend/
COPY --from=frontend /build/build /app/frontend
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /data && chown -R fitforge:fitforge /data /app

EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["app"]
