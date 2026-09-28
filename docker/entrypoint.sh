#!/bin/sh
# FitForge Entrypoint: PUID/PGID übernehmen, Verzeichnisse vorbereiten, Migrationen, dann als Nicht-Root starten.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
  if [ "$(id -g fitforge)" != "$PGID" ]; then groupmod -o -g "$PGID" fitforge; fi
  if [ "$(id -u fitforge)" != "$PUID" ]; then usermod -o -u "$PUID" fitforge; fi
  mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/backups"
  chown fitforge:fitforge "$DATA_DIR" "$DATA_DIR/uploads" "$DATA_DIR/backups"
  exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups "$0" "$@"
fi

case "$1" in
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
    # Warten, bis die App die Migrationen ausgeführt hat
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
