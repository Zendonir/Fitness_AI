#!/bin/sh
# FitForge Entrypoint
#  - erzeugt beim ersten Start alle Schlüssel automatisch (SECRETS_DIR, Standard /data/secrets)
#  - übernimmt PUID/PGID, bereitet Verzeichnisse vor, führt Migrationen aus
#  - startet als Nicht-Root
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
SECRETS_DIR="${SECRETS_DIR:-/data/secrets}"

# Umgebungsvariable aus Datei setzen, falls nicht explizit gesetzt
load_secret() {
  var="$1"; file="$SECRETS_DIR/$2"
  eval "cur=\${$var:-}"
  if [ -z "$cur" ] && [ -f "$file" ]; then
    export "$var=$(cat "$file")"
  fi
}

if [ "$(id -u)" = "0" ]; then
  if [ "$1" = "init" ]; then
    exec python -m app.cli init-secrets "$SECRETS_DIR"
  fi
  if [ "$(id -g fitforge)" != "$PGID" ]; then groupmod -o -g "$PGID" fitforge; fi
  if [ "$(id -u fitforge)" != "$PUID" ]; then usermod -o -u "$PUID" fitforge; fi
  mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/backups"
  chown fitforge:fitforge "$DATA_DIR" "$DATA_DIR/uploads" "$DATA_DIR/backups"
  # Schlüssel als root lesen, dann als Umgebungsvariablen an den Nicht-Root-Prozess weitergeben
  if [ -d "$SECRETS_DIR" ]; then
    load_secret SECRET_KEY secret_key
    load_secret FERNET_KEY fernet_key
    load_secret VAPID_PUBLIC_KEY vapid_public_key
    load_secret VAPID_PRIVATE_KEY vapid_private_key
    if [ -z "${DATABASE_URL:-}" ] && [ -f "$SECRETS_DIR/postgres_password" ]; then
      export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-fitforge}:$(cat "$SECRETS_DIR/postgres_password")@${POSTGRES_HOST:-postgres}:5432/${POSTGRES_DB:-fitforge}"
    fi
  fi
  export HOME=/app
  exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups "$0" "$@"
fi

case "$1" in
  init)
    exec python -m app.cli init-secrets "$SECRETS_DIR"
    ;;
  app)
    echo "[fitforge] Warte auf Datenbank und führe Migrationen aus …"
    i=0
    until alembic upgrade head; do
      i=$((i+1))
      if [ "$i" -ge 30 ]; then echo "[fitforge] Datenbank nicht erreichbar – Abbruch"; exit 1; fi
      sleep 2
    done
    exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*" \
      --workers "${WEB_WORKERS:-1}"
    ;;
  worker)
    sleep "${WORKER_START_DELAY:-10}"
    exec arq app.worker.WorkerSettings
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  backup)
    exec python -c "import asyncio; from app.services.backup import run_backup; print(asyncio.run(run_backup()))"
    ;;
  create-admin)
    shift
    exec python -m app.cli create-admin "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
