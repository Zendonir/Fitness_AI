import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import router as api_router
from app.core import db as dbmod
from app.core.config import settings

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fitforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (settings.uploads_dir, settings.backups_dir):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning("Verzeichnis %s nicht anlegbar: %s", d, e)
    from app.services.bootstrap import seed_database

    async with dbmod.session_scope() as db:
        await seed_database(db)
    yield


app = FastAPI(
    title="FitForge API",
    version="1.0.0",
    description="Self-hosted Trainings- & Ernährungstracker mit KI-Coach. "
    "Authentifizierung per Session-Cookie oder `Authorization: Bearer ff_…` (persönlicher API-Token).",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api")


@app.get("/api/health", tags=["system"])
async def health() -> dict:
    async with dbmod.session_scope() as db:
        await db.exec(text("SELECT 1"))  # type: ignore[call-overload]
    return {"status": "ok"}


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ---------------------------------------------------------------- Frontend (SPA)
FRONTEND = Path(settings.frontend_dir)
if FRONTEND.exists():
    if (FRONTEND / "_app").exists():
        app.mount("/_app", StaticFiles(directory=FRONTEND / "_app"), name="app-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (FRONTEND / path).resolve()
        if path and candidate.is_file() and FRONTEND.resolve() in candidate.parents:
            headers = {"Cache-Control": "no-cache"} if path in ("sw.js", "manifest.webmanifest") else None
            return FileResponse(candidate, headers=headers)
        return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
