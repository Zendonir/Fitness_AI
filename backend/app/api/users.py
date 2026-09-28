from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlmodel import func, select

from app.api.auth import user_out
from app.core.access import RESOURCE_TYPES, get_writable, not_found
from app.core.deps import DB, SESSION_COOKIE, CurrentUser
from app.core.security import verify_password
from app.models import (
    CoachProfile,
    Exercise,
    Food,
    Plan,
    Recipe,
    Role,
    ShareGrant,
    TrainerComment,
    TrainerLink,
    User,
    UserProfile,
)
from app.services.app_settings import get_user_settings, update_user_settings
from app.services.audit import audit
from app.services.nutrition import validate_targets, body_from_profile
from app.services.targets import latest_weight, user_targets

router = APIRouter(tags=["me"])


# ---------------------------------------------------------------- settings
@router.get("/me/settings")
async def get_settings(user: CurrentUser, db: DB) -> dict[str, Any]:
    return await get_user_settings(db, user.id)


@router.patch("/me/settings")
async def patch_settings(patch: dict[str, Any], user: CurrentUser, db: DB) -> dict[str, Any]:
    return await update_user_settings(db, user.id, patch)


class AccountPatch(BaseModel):
    display_name: str | None = None
    email: EmailStr | None = None


@router.patch("/me")
async def patch_me(body: AccountPatch, user: CurrentUser, db: DB) -> dict[str, Any]:
    if body.display_name is not None:
        user.display_name = body.display_name[:120]
    if body.email and body.email.lower() != user.email:
        exists = (await db.exec(select(User).where(func.lower(User.email) == body.email.lower()))).first()
        if exists:
            raise HTTPException(409, "E-Mail bereits vergeben")
        user.email = body.email.lower()
    db.add(user)
    await db.commit()
    return user_out(user)


# ---------------------------------------------------------------- profile / targets
class ProfileIn(BaseModel):
    sex: Literal["male", "female"] | None = None
    birth_date: date | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"] | None = None
    goal: Literal["bulk", "maintain", "cut"] | None = None
    training_days_per_week: int | None = None
    custom_targets: dict[str, Any] | None = None


async def _profile(db: DB, user_id: int) -> UserProfile:
    p = await db.get(UserProfile, user_id)
    if not p:
        p = UserProfile(user_id=user_id)
        db.add(p)
        await db.commit()
    return p


@router.get("/me/profile")
async def get_profile(user: CurrentUser, db: DB) -> dict[str, Any]:
    p = await _profile(db, user.id)
    return {"profile": p.model_dump(), "targets": await user_targets(db, user.id)}


@router.put("/me/profile")
async def put_profile(body: ProfileIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    p = await _profile(db, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    if p.custom_targets:
        b = body_from_profile(p, await latest_weight(db, user.id))
        p.custom_targets = {
            k: validate_targets(v, b) for k, v in p.custom_targets.items() if k in ("training", "rest") and v
        }
    db.add(p)
    await db.commit()
    return {"profile": p.model_dump(), "targets": await user_targets(db, user.id)}


@router.get("/me/targets")
async def get_targets(user: CurrentUser, db: DB, day: date | None = None) -> dict[str, Any]:
    return await user_targets(db, user.id, day)


# ---------------------------------------------------------------- onboarding
class OnboardingIn(BaseModel):
    profile: ProfileIn
    coach: dict[str, str] = {}
    settings: dict[str, Any] = {}
    plan_template_id: int | None = None


@router.post("/me/onboarding")
async def onboarding(body: OnboardingIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    await put_profile(body.profile, user, db)
    if body.coach:
        cp = await db.get(CoachProfile, user.id) or CoachProfile(user_id=user.id)
        for k in ("goals", "experience", "preferences", "dislikes", "limitations", "equipment", "schedule"):
            if k in body.coach:
                setattr(cp, k, body.coach[k])
        db.add(cp)
    if body.settings:
        await update_user_settings(db, user.id, body.settings)
    if body.plan_template_id:
        from app.api.training import copy_plan

        plan = await copy_plan(db, body.plan_template_id, user)
        plan.is_active = True
        plan.started_on = date.today()
        db.add(plan)
    if body.profile.weight_kg:
        from app.models import BodyMeasurement

        db.add(BodyMeasurement(user_id=user.id, day=date.today(), weight_kg=body.profile.weight_kg))
    user.onboarding_done = True
    db.add(user)
    await db.commit()
    return {"user": user_out(user)}


# ---------------------------------------------------------------- directory (für Teilen / Trainer)
@router.get("/users/directory")
async def directory(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(User).where(User.is_active, User.id != user.id))).all()
    return [{"id": u.id, "display_name": u.display_name, "role": u.role} for u in rows]


# ---------------------------------------------------------------- sharing
MODELS = {"plan": Plan, "recipe": Recipe, "food": Food, "exercise": Exercise}


class ShareIn(BaseModel):
    visibility: Literal["private", "shared", "public"]
    user_ids: list[int] = []


@router.get("/share/{rtype}/{rid}")
async def get_share(rtype: str, rid: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    if rtype not in RESOURCE_TYPES:
        raise not_found()
    obj = await get_writable(db, MODELS[rtype], rtype, rid, user)
    grants = (
        await db.exec(select(ShareGrant).where(ShareGrant.resource_type == rtype, ShareGrant.resource_id == rid))
    ).all()
    return {"visibility": obj.visibility, "user_ids": [g.user_id for g in grants]}


@router.put("/share/{rtype}/{rid}")
async def put_share(rtype: str, rid: int, body: ShareIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    if rtype not in RESOURCE_TYPES:
        raise not_found()
    obj = await get_writable(db, MODELS[rtype], rtype, rid, user)
    obj.visibility = body.visibility
    db.add(obj)
    for g in (
        await db.exec(select(ShareGrant).where(ShareGrant.resource_type == rtype, ShareGrant.resource_id == rid))
    ).all():
        await db.delete(g)
    if body.visibility == "shared":
        for uid in set(body.user_ids):
            if uid != user.id and await db.get(User, uid):
                db.add(ShareGrant(resource_type=rtype, resource_id=rid, user_id=uid))
    await db.commit()
    return await get_share(rtype, rid, user, db)


# ---------------------------------------------------------------- trainer
class TrainerIn(BaseModel):
    trainer_id: int


@router.get("/me/trainers")
async def my_trainers(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(TrainerLink).where(TrainerLink.athlete_id == user.id))).all()
    out = []
    for r in rows:
        t = await db.get(User, r.trainer_id)
        if t:
            out.append({"id": r.id, "trainer_id": t.id, "display_name": t.display_name})
    return out


@router.post("/me/trainers")
async def add_trainer(body: TrainerIn, user: CurrentUser, db: DB) -> dict[str, bool]:
    t = await db.get(User, body.trainer_id)
    if not t or t.role not in (Role.trainer, Role.admin) or t.id == user.id:
        raise HTTPException(400, "Kein Trainer")
    exists = (
        await db.exec(select(TrainerLink).where(TrainerLink.trainer_id == t.id, TrainerLink.athlete_id == user.id))
    ).first()
    if not exists:
        db.add(TrainerLink(trainer_id=t.id, athlete_id=user.id))
        await audit(db, "trainer_granted", actor_id=user.id, target=str(t.id))
    return {"ok": True}


@router.delete("/me/trainers/{link_id}")
async def remove_trainer(link_id: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    link = await db.get(TrainerLink, link_id)
    if not link or link.athlete_id != user.id:
        raise not_found()
    await db.delete(link)
    await db.commit()
    return {"ok": True}


@router.get("/trainer/athletes")
async def trainer_athletes(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(TrainerLink).where(TrainerLink.trainer_id == user.id))).all()
    out = []
    for r in rows:
        a = await db.get(User, r.athlete_id)
        if a and a.is_active:
            out.append({"id": a.id, "display_name": a.display_name})
    return out


class CommentIn(BaseModel):
    athlete_id: int
    text: str
    target_type: str = "general"
    target_id: int | None = None


@router.post("/trainer/comments")
async def trainer_comment(body: CommentIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    link = (
        await db.exec(
            select(TrainerLink).where(TrainerLink.trainer_id == user.id, TrainerLink.athlete_id == body.athlete_id)
        )
    ).first()
    if not link:
        raise HTTPException(403, "Keine Freigabe")
    c = TrainerComment(
        trainer_id=user.id, athlete_id=body.athlete_id, text=body.text[:4000],
        target_type=body.target_type, target_id=body.target_id,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    from app.services.push import notify_user

    await notify_user(db, body.athlete_id, "Neuer Trainer-Kommentar", body.text[:120], url="/profile", kind="hints")
    return c.model_dump()


@router.get("/me/comments")
async def my_comments(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (
        await db.exec(
            select(TrainerComment)
            .where((TrainerComment.athlete_id == user.id) | (TrainerComment.trainer_id == user.id))
            .order_by(TrainerComment.created_at.desc())
            .limit(100)
        )
    ).all()
    names: dict[int, str] = {}
    out = []
    for r in rows:
        if r.trainer_id not in names:
            t = await db.get(User, r.trainer_id)
            names[r.trainer_id] = t.display_name if t else "?"
        out.append({**r.model_dump(), "trainer_name": names[r.trainer_id]})
    return out


# ---------------------------------------------------------------- account deletion
class DeleteIn(BaseModel):
    password: str | None = None
    confirm: str


@router.delete("/me")
async def delete_account(body: DeleteIn, response: Response, user: CurrentUser, db: DB) -> dict[str, bool]:
    if body.confirm != "LÖSCHEN":
        raise HTTPException(400, 'Bitte zur Bestätigung „LÖSCHEN" eingeben')
    if user.password_hash and not verify_password(body.password or "", user.password_hash):
        raise HTTPException(400, "Passwort falsch")
    if user.role == Role.admin:
        admins = (await db.exec(select(func.count()).select_from(User).where(User.role == Role.admin))).one()
        if admins <= 1:
            raise HTTPException(400, "Der letzte Administrator kann nicht gelöscht werden")
    from app.services.export import delete_user_data

    await delete_user_data(db, user)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
