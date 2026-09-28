"""Nächtliches pg_dump-Backup mit Aufbewahrungsregel (täglich/wöchentlich/monatlich)."""

import asyncio
import gzip
import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings

log = logging.getLogger(__name__)


def _pg_env() -> tuple[list[str], dict[str, str]]:
    url = urlparse(settings.database_url.replace("+asyncpg", ""))
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    args = ["-h", url.hostname or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres",
            "-d", (url.path or "/fitforge").lstrip("/")]
    return args, env


async def run_backup() -> dict:
    d = settings.backups_dir
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = d / f"fitforge_{stamp}.sql.gz"
    args, env = _pg_env()
    proc = await asyncio.create_subprocess_exec(
        "pg_dump", "--no-owner", "--no-privileges", "--clean", "--if-exists", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        log.error("pg_dump fehlgeschlagen: %s", err.decode()[:500])
        return {"ok": False, "error": err.decode()[:500]}
    target.write_bytes(gzip.compress(out))
    removed = apply_retention(d)
    log.info("Backup %s geschrieben (%d Bytes), %d alte entfernt", target.name, target.stat().st_size, len(removed))
    return {"ok": True, "file": target.name, "bytes": target.stat().st_size, "removed": removed}


def _stamp(p: Path) -> datetime | None:
    try:
        return datetime.strptime(p.name.removeprefix("fitforge_").removesuffix(".sql.gz"), "%Y-%m-%d_%H%M%S")
    except ValueError:
        return None


def select_keep(stamps: list[datetime], daily: int, weekly: int, monthly: int) -> set[datetime]:
    """Grandfather-Father-Son: neueste pro Tag/Woche/Monat behalten."""
    keep: set[datetime] = set()
    ordered = sorted(stamps, reverse=True)
    for key_fn, n in (
        (lambda t: t.date(), daily),
        (lambda t: t.isocalendar()[:2], weekly),
        (lambda t: (t.year, t.month), monthly),
    ):
        seen: list = []
        for t in ordered:
            k = key_fn(t)
            if k not in seen:
                seen.append(k)
                if len(seen) <= n:
                    keep.add(t)
    return keep


def apply_retention(d: Path) -> list[str]:
    files = {s: p for p in d.glob("fitforge_*.sql.gz") if (s := _stamp(p))}
    keep = select_keep(list(files), settings.backup_keep_daily, settings.backup_keep_weekly, settings.backup_keep_monthly)
    removed = []
    for s, p in files.items():
        if s not in keep:
            p.unlink(missing_ok=True)
            removed.append(p.name)
    return removed


async def enqueue_or_run_backup() -> dict:
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        job = await pool.enqueue_job("backup_job")
        await pool.aclose()
        return {"queued": True, "job_id": job.job_id if job else None}
    except Exception as e:  # noqa: BLE001 - Redis nicht erreichbar -> direkt ausführen
        log.warning("Redis nicht erreichbar (%s), Backup läuft direkt", e)
        return await run_backup()
