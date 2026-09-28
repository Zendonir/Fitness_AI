from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlmodel import func, select

from app.core.config import settings
from app.core.deps import DB, AdminUser, client_ip
from app.core.urls import base_url
from app.core.security import encrypt, hash_password, hash_token, mask_secret, new_token, decrypt, validate_password
from app.models import (
    AIUsage,
    AuditLog,
    Invite,
    MealEntry,
    PasswordReset,
    Plan,
    PromptTemplate,
    Role,
    Session,
    User,
    Workout,
    WorkoutSet,
)
from app.services.app_settings import get_app_setting, set_app_setting, system_flags
from app.services.audit import audit

router = APIRouter(prefix="/admin", tags=["admin"])


def _dir_size(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def month_start(d: date | None = None) -> datetime:
    d = d or date.today()
    return datetime(d.year, d.month, 1, tzinfo=UTC)


@router.get("/users")
async def list_users(admin: AdminUser, db: DB) -> list[dict[str, Any]]:
    users = (await db.exec(select(User).order_by(User.id))).all()
    ms = month_start()
    costs = dict(
        (await db.exec(
            select(AIUsage.user_id, func.sum(AIUsage.cost_usd)).where(AIUsage.created_at >= ms).group_by(AIUsage.user_id)
        )).all()
    )
    default_limit = (await system_flags(db))["default_monthly_limit_usd"]
    out = []
    for u in users:
        n_sets = (await db.exec(select(func.count()).select_from(WorkoutSet).where(WorkoutSet.user_id == u.id))).one()
        n_meals = (await db.exec(select(func.count()).select_from(MealEntry).where(MealEntry.user_id == u.id))).one()
        out.append(
            {
                "id": u.id, "email": u.email, "display_name": u.display_name, "role": u.role,
                "is_active": u.is_active, "created_at": u.created_at, "last_login_at": u.last_login_at,
                "totp_enabled": u.totp_enabled,
                "ai_monthly_limit_usd": u.ai_monthly_limit_usd, "ai_effective_limit": u.ai_monthly_limit_usd
                if u.ai_monthly_limit_usd is not None else default_limit,
                "ai_cost_month": round(float(costs.get(u.id) or 0), 4),
                "storage": {
                    "photos_bytes": _dir_size(settings.uploads_dir / str(u.id)),
                    "sets": n_sets, "meal_entries": n_meals,
                },
            }
        )
    return out


class CreateUserIn(BaseModel):
    email: EmailStr
    display_name: str = ""
    role: Role = Role.user
    password: str | None = None


@router.post("/users")
async def create_user(body: CreateUserIn, request: Request, admin: AdminUser, db: DB) -> dict[str, Any]:
    if (await db.exec(select(User).where(func.lower(User.email) == body.email.lower()))).first():
        raise HTTPException(409, "E-Mail bereits vorhanden")
    if body.password and (err := validate_password(body.password)):
        raise HTTPException(422, err)
    u = User(
        email=body.email.lower(), display_name=body.display_name or body.email.split("@")[0], role=body.role,
        password_hash=hash_password(body.password) if body.password else None,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    from app.services.bootstrap import init_user

    await init_user(db, u)
    reset_url = None
    if not body.password:
        reset_url = await _reset_link(db, u, base_url(request))
    await audit(db, "admin_user_created", actor_id=admin.id, target=u.email, ip=client_ip(request))
    return {"id": u.id, "reset_url": reset_url}


class PatchUserIn(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    display_name: str | None = None
    ai_monthly_limit_usd: float | None = None
    clear_ai_limit: bool = False


@router.patch("/users/{uid}")
async def patch_user(uid: int, body: PatchUserIn, request: Request, admin: AdminUser, db: DB) -> dict[str, bool]:
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(404, "Nicht gefunden")
    if u.id == admin.id and (body.is_active is False or (body.role and body.role != Role.admin)):
        raise HTTPException(400, "Du kannst dich nicht selbst sperren oder degradieren")
    data = body.model_dump(exclude_unset=True, exclude={"clear_ai_limit"})
    for k, v in data.items():
        setattr(u, k, v)
    if body.clear_ai_limit:
        u.ai_monthly_limit_usd = None
    db.add(u)
    if body.is_active is False:
        for s in (await db.exec(select(Session).where(Session.user_id == u.id))).all():
            await db.delete(s)
    await audit(db, "admin_user_updated", actor_id=admin.id, target=u.email, details=data, ip=client_ip(request))
    return {"ok": True}


@router.delete("/users/{uid}")
async def delete_user(uid: int, request: Request, admin: AdminUser, db: DB) -> dict[str, bool]:
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(404, "Nicht gefunden")
    if u.id == admin.id:
        raise HTTPException(400, "Eigenes Konto bitte über das Profil löschen")
    email = u.email
    from app.services.export import delete_user_data

    await delete_user_data(db, u)
    await audit(db, "admin_user_deleted", actor_id=admin.id, target=email, ip=client_ip(request))
    return {"ok": True}


async def _reset_link(db: DB, u: User, base: str = "", hours: int = 48) -> str:
    token = new_token()
    db.add(PasswordReset(token_hash=hash_token(token), user_id=u.id,
                         expires_at=datetime.now(UTC) + timedelta(hours=hours)))
    await db.commit()
    return f"{base or base_url()}/reset?token={token}"


@router.post("/users/{uid}/reset-link")
async def reset_link(uid: int, request: Request, admin: AdminUser, db: DB) -> dict[str, str]:
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(404, "Nicht gefunden")
    url = await _reset_link(db, u, base_url(request))
    await audit(db, "admin_reset_link", actor_id=admin.id, target=u.email, ip=client_ip(request))
    return {"url": url}


# ---------------------------------------------------------------- invites
class InviteIn(BaseModel):
    email: EmailStr | None = None
    role: Role = Role.user
    days: int = 7


@router.get("/invites")
async def list_invites(admin: AdminUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(Invite).order_by(Invite.created_at.desc()).limit(100))).all()
    return [
        {"id": r.id, "email": r.email, "role": r.role, "created_at": r.created_at, "expires_at": r.expires_at,
         "used_at": r.used_at}
        for r in rows
    ]


@router.post("/invites")
async def create_invite(body: InviteIn, request: Request, admin: AdminUser, db: DB) -> dict[str, Any]:
    token = new_token(nbytes=24)
    inv = Invite(
        token_hash=hash_token(token), email=body.email.lower() if body.email else None, role=body.role,
        created_by=admin.id, expires_at=datetime.now(UTC) + timedelta(days=max(1, min(body.days, 60))),
    )
    db.add(inv)
    await db.commit()
    await audit(db, "invite_created", actor_id=admin.id, target=body.email or "", ip=client_ip(request))
    return {"id": inv.id, "url": f"{base_url(request)}/register?invite={token}", "expires_at": inv.expires_at}


@router.delete("/invites/{iid}")
async def delete_invite(iid: int, admin: AdminUser, db: DB) -> dict[str, bool]:
    inv = await db.get(Invite, iid)
    if inv:
        await db.delete(inv)
        await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- global settings
class AdminSettingsIn(BaseModel):
    open_registration: bool | None = None
    ai_enabled: bool | None = None
    default_monthly_limit_usd: float | None = None
    default_provider: Literal["anthropic", "openai", "ollama"] | None = None
    default_models: dict[str, str] | None = None
    user_defaults: dict[str, Any] | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    ollama_base_url: str | None = None


@router.get("/settings")
async def get_admin_settings(admin: AdminUser, db: DB) -> dict[str, Any]:
    keys = await get_app_setting(db, "ai_keys", {})
    return {
        **await system_flags(db),
        "default_models": await get_app_setting(db, "default_models", {}),
        "user_defaults": await get_app_setting(db, "user_defaults", {}),
        "keys": {
            "anthropic": mask_secret(decrypt(keys.get("anthropic"))) or ("ENV" if settings.anthropic_api_key else ""),
            "openai": mask_secret(decrypt(keys.get("openai"))) or ("ENV" if settings.openai_api_key else ""),
            "ollama_base_url": keys.get("ollama_base_url") or settings.ollama_base_url,
        },
        "push_configured": bool(settings.vapid_private_key),
        "oidc_enabled": settings.oidc_enabled,
    }


@router.patch("/settings")
async def patch_admin_settings(body: AdminSettingsIn, request: Request, admin: AdminUser, db: DB) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    for key in ("open_registration", "ai_enabled", "default_monthly_limit_usd", "default_provider",
                "default_models", "user_defaults"):
        if key in data:
            await set_app_setting(db, key, data[key])
    if any(k in data for k in ("anthropic_api_key", "openai_api_key", "ollama_base_url")):
        keys = dict(await get_app_setting(db, "ai_keys", {}))
        for prov in ("anthropic", "openai"):
            v = data.get(f"{prov}_api_key")
            if v is not None:
                keys[prov] = encrypt(v) if v else None
        if "ollama_base_url" in data:
            keys["ollama_base_url"] = data["ollama_base_url"]
        await set_app_setting(db, "ai_keys", keys)
    safe = {k: v for k, v in data.items() if "key" not in k}
    await audit(db, "admin_settings", actor_id=admin.id, details=safe, ip=client_ip(request))
    return await get_admin_settings(admin, db)


# ---------------------------------------------------------------- audit / costs / storage
@router.get("/audit")
async def audit_log(admin: AdminUser, db: DB, limit: int = 100, offset: int = 0, action: str | None = None) -> list[dict[str, Any]]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(min(limit, 500))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = (await db.exec(stmt)).all()
    emails = {u.id: u.email for u in (await db.exec(select(User))).all()}
    return [{**r.model_dump(), "actor": emails.get(r.actor_id, "")} for r in rows]


@router.get("/ai-usage")
async def ai_usage(admin: AdminUser, db: DB, months: int = 6) -> dict[str, Any]:
    since = month_start() - timedelta(days=31 * (months - 1))
    since = datetime(since.year, since.month, 1, tzinfo=UTC)
    rows = (await db.exec(select(AIUsage).where(AIUsage.created_at >= since))).all()
    emails = {u.id: u.display_name or u.email for u in (await db.exec(select(User))).all()}
    agg: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        ts = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC)
        key = (ts.strftime("%Y-%m"), r.user_id, r.provider)
        a = agg.setdefault(key, {"month": key[0], "user_id": r.user_id, "user": emails.get(r.user_id, "System"),
                                 "provider": r.provider, "requests": 0, "input_tokens": 0, "output_tokens": 0,
                                 "cost_usd": 0.0, "errors": 0})
        a["requests"] += 1
        a["input_tokens"] += r.input_tokens
        a["output_tokens"] += r.output_tokens
        a["cost_usd"] = round(a["cost_usd"] + r.cost_usd, 5)
        a["errors"] += 0 if r.success else 1
    return {"rows": sorted(agg.values(), key=lambda x: (x["month"], x["user"]), reverse=True)}


@router.get("/ai-log")
async def ai_log(admin: AdminUser, db: DB, limit: int = 100) -> list[dict[str, Any]]:
    rows = (await db.exec(select(AIUsage).order_by(AIUsage.created_at.desc()).limit(min(limit, 500)))).all()
    return [r.model_dump() for r in rows]


@router.get("/storage")
async def storage(admin: AdminUser, db: DB) -> dict[str, Any]:
    db_size = None
    try:
        db_size = (await db.exec(text("SELECT pg_database_size(current_database())"))).one()[0]  # type: ignore[call-overload]
    except Exception:  # noqa: BLE001 - SQLite in Tests
        db_size = None
    return {
        "database_bytes": db_size,
        "uploads_bytes": _dir_size(settings.uploads_dir),
        "backups_bytes": _dir_size(settings.backups_dir),
        "users": (await db.exec(select(func.count()).select_from(User))).one(),
        "workouts": (await db.exec(select(func.count()).select_from(Workout))).one(),
    }


# ---------------------------------------------------------------- prompts (versioniert)
class PromptIn(BaseModel):
    content: str
    comment: str = ""


@router.get("/prompts")
async def list_prompts(admin: AdminUser, db: DB, name: str = "coach_system") -> list[dict[str, Any]]:
    rows = (await db.exec(select(PromptTemplate).where(PromptTemplate.name == name).order_by(PromptTemplate.version.desc()))).all()
    return [r.model_dump() for r in rows]


@router.post("/prompts")
async def new_prompt(body: PromptIn, request: Request, admin: AdminUser, db: DB, name: str = "coach_system") -> dict[str, Any]:
    latest = (await db.exec(select(func.max(PromptTemplate.version)).where(PromptTemplate.name == name))).one() or 0
    for r in (await db.exec(select(PromptTemplate).where(PromptTemplate.name == name, PromptTemplate.is_active))).all():
        r.is_active = False
        db.add(r)
    p = PromptTemplate(name=name, version=latest + 1, content=body.content, comment=body.comment, is_active=True,
                       created_by=admin.id)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    await audit(db, "prompt_version", actor_id=admin.id, target=f"{name} v{p.version}", ip=client_ip(request))
    return p.model_dump()


@router.post("/prompts/{pid}/activate")
async def activate_prompt(pid: int, admin: AdminUser, db: DB) -> dict[str, bool]:
    p = await db.get(PromptTemplate, pid)
    if not p:
        raise HTTPException(404, "Nicht gefunden")
    for r in (await db.exec(select(PromptTemplate).where(PromptTemplate.name == p.name, PromptTemplate.is_active))).all():
        r.is_active = False
        db.add(r)
    p.is_active = True
    db.add(p)
    await audit(db, "prompt_activated", actor_id=admin.id, target=f"{p.name} v{p.version}")
    return {"ok": True}


# ---------------------------------------------------------------- globale Vorlagen
@router.post("/templates/plan/{plan_id}")
async def make_global_plan(plan_id: int, admin: AdminUser, db: DB) -> dict[str, Any]:
    from app.api.training import copy_plan

    src = await db.get(Plan, plan_id)
    if not src:
        raise HTTPException(404, "Nicht gefunden")
    plan = await copy_plan(db, plan_id, admin, as_global=True)
    await audit(db, "global_template_created", actor_id=admin.id, target=plan.name)
    return {"id": plan.id}


# ---------------------------------------------------------------- backups
@router.get("/backups")
async def list_backups(admin: AdminUser) -> list[dict[str, Any]]:
    d = settings.backups_dir
    if not d.exists():
        return []
    files = sorted(d.glob("*.sql.gz"), reverse=True)
    return [{"name": f.name, "bytes": f.stat().st_size, "created": datetime.fromtimestamp(f.stat().st_mtime, UTC)} for f in files]


@router.post("/backups")
async def backup_now(admin: AdminUser, db: DB) -> dict[str, Any]:
    from app.services.backup import enqueue_or_run_backup

    result = await enqueue_or_run_backup()
    await audit(db, "backup_triggered", actor_id=admin.id)
    return result


# ---------------------------------------------------------------- Lebensmitteldatenbank (BLS)
@router.get("/food-db")
async def food_db_status(admin: AdminUser, db: DB) -> dict[str, Any]:
    from app.models import Food
    from app.services.bls import bls_status

    counts = dict((await db.exec(select(Food.source, func.count()).where(Food.owner_id.is_(None)).group_by(Food.source))).all())
    return {"bls": await bls_status(db), "counts": counts}


@router.post("/food-db/bls/import")
async def food_db_import(admin: AdminUser, db: DB) -> dict[str, Any]:
    """BLS herunterladen und importieren (im Worker, sonst direkt)."""
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        job = await pool.enqueue_job("bls_import_job", _job_id="bls-import")
        await pool.aclose()
        await audit(db, "food_db_import", actor_id=admin.id)
        return {"queued": True, "job_id": job.job_id if job else "bls-import"}
    except Exception:  # noqa: BLE001 - kein Redis → direkt importieren
        from app.services.bls import BLSImportError, import_bls

        try:
            return await import_bls(db)
        except BLSImportError as e:
            raise HTTPException(502, str(e)) from e


@router.post("/food-db/bls/upload")
async def food_db_upload(admin: AdminUser, db: DB, file: UploadFile = File(...)) -> dict[str, Any]:
    """BLS-Datei (xlsx oder csv von blsdb.de) hochladen und importieren."""
    from app.services.bls import BLSImportError, import_bls

    target = settings.data_dir / "food-db" / f"upload_{(file.filename or 'bls.xlsx').replace('/', '_')}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(await file.read())
    try:
        status = await import_bls(db, path=target)
    except BLSImportError as e:
        raise HTTPException(422, str(e)) from e
    await audit(db, "food_db_upload", actor_id=admin.id, details={"count": status["count"]})
    return status
