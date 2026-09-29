"""Übungsanimationen über den Server ausliefern (lokaler Cache vor dem CDN)."""

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.deps import CurrentUser
from app.services import media_cache

router = APIRouter(tags=["media"])

# Dateien sind versioniert und ändern sich nie -> dauerhaft im Browser cachen
IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}


@router.get("/media/{path:path}", include_in_schema=False)
async def media(path: str, user: CurrentUser) -> FileResponse:
    if not media_cache.valid_path(path):
        raise HTTPException(404, "Nicht gefunden")
    try:
        file = await media_cache.fetch(path)
    except media_cache.MediaNotFound:
        raise HTTPException(404, "Nicht gefunden") from None
    except httpx.HTTPError:
        raise HTTPException(502, "Animation gerade nicht erreichbar") from None
    headers = {"Cache-Control": "private, max-age=86400"} if path.endswith(".json") else IMMUTABLE
    return FileResponse(file, media_type=media_cache.content_type(path), headers=headers)
