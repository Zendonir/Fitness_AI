"""Lokaler Zwischenspeicher für Übungsanimationen (ExerciseGymGifsDB).

Der Server lädt jede Animation einmal vom CDN (oder eigenen Spiegel) und liefert sie danach aus
``/data/media-cache`` aus – im Heimnetz deutlich schneller als der Umweg über das CDN. Der Cache ist
temporär: er wird beim Überschreiten von ``MEDIA_CACHE_MAX_MB`` bereinigt (älteste Zugriffe zuerst)
und kann jederzeit gelöscht werden.
"""

import asyncio
import logging
import os
import re
from pathlib import Path

import httpx

from app.core.config import settings
from app.seed.exercise_media import MEDIA_VERSION

log = logging.getLogger(__name__)

# Nur Pfade der Bibliothek – der Endpunkt darf kein offener Proxy sein
_PATH_RE = re.compile(r"^(?:[a-z0-9-]+/[a-z0-9-]+\.(?:gif|thumb\.webp)|api/(?:en|es)/muscles/[a-z0-9-]+\.json)$")
MAX_FILE_BYTES = 15 * 1024 * 1024
CONTENT_TYPES = {".gif": "image/gif", ".webp": "image/webp", ".json": "application/json"}

_locks: dict[str, asyncio.Lock] = {}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, follow_redirects=True)


def valid_path(path: str) -> bool:
    return bool(_PATH_RE.fullmatch(path))


def cache_dir() -> Path:
    # Pro Upstream-Version eigener Ordner: IDs sind an die Version gebunden
    return settings.media_cache_dir / MEDIA_VERSION


def content_type(path: str) -> str:
    return CONTENT_TYPES.get(Path(path).suffix, "application/octet-stream")


class MediaNotFound(Exception):
    pass


async def fetch(path: str, client: httpx.AsyncClient | None = None) -> Path:
    """Datei aus dem Cache liefern, fehlende Dateien einmalig vom Upstream laden."""
    if not valid_path(path):
        raise MediaNotFound(path)
    target = cache_dir() / path
    if target.is_file():
        _touch(target)
        return target
    lock = _locks.setdefault(path, asyncio.Lock())
    async with lock:
        if target.is_file():
            return target
        own = client is None
        client = client or _client()
        try:
            res = await client.get(f"{settings.media_base}/{path}")
        finally:
            if own:
                await client.aclose()
        if res.status_code == 404:
            raise MediaNotFound(path)
        res.raise_for_status()
        if len(res.content) > MAX_FILE_BYTES:
            raise MediaNotFound(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        tmp.write_bytes(res.content)
        tmp.replace(target)
    _locks.pop(path, None)
    return target


def _touch(p: Path) -> None:
    try:
        os.utime(p)  # Zugriffszeit für die Bereinigung (atime ist oft deaktiviert)
    except OSError:
        pass


def stats() -> dict:
    files = [p for p in settings.media_cache_dir.rglob("*") if p.is_file()] if settings.media_cache_dir.exists() else []
    return {"files": len(files), "bytes": sum(p.stat().st_size for p in files)}


def prune(max_bytes: int | None = None) -> int:
    """Alte Versionen entfernen und auf die Maximalgröße kürzen (zuletzt benutzte bleiben)."""
    root = settings.media_cache_dir
    if not root.exists():
        return 0
    removed = 0
    current = cache_dir()
    for p in root.rglob("*"):
        if p.is_file() and current not in p.parents:
            p.unlink(missing_ok=True)
            removed += 1
    limit = settings.media_cache_max_mb * 1024 * 1024 if max_bytes is None else max_bytes
    files = sorted((p for p in current.rglob("*") if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    for p in files:
        if total <= limit:
            break
        total -= p.stat().st_size
        p.unlink(missing_ok=True)
        removed += 1
    return removed


async def warm(media_ids: list[str], concurrency: int = 4) -> dict:
    """Animationen vorab laden (Thumbnails und GIFs der verwendeten Übungen)."""
    paths = [f"{m}{ext}" for m in dict.fromkeys(media_ids) for ext in (".thumb.webp", ".gif")]
    todo = [p for p in paths if valid_path(p) and not (cache_dir() / p).is_file()]
    ok = failed = 0
    sem = asyncio.Semaphore(concurrency)
    async with _client() as client:
        async def one(p: str) -> None:
            nonlocal ok, failed
            async with sem:
                try:
                    await fetch(p, client)
                    ok += 1
                except Exception:  # noqa: BLE001 - einzelne fehlende Dateien sind kein Abbruchgrund
                    failed += 1

        await asyncio.gather(*(one(p) for p in todo))
    if todo:
        log.info("Übungsanimationen vorgeladen: %s neu, %s fehlgeschlagen", ok, failed)
    return {"loaded": ok, "failed": failed, "cached": len(paths) - len(todo)}
