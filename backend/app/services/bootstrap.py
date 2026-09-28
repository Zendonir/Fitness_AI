"""Seed-Daten und Initialisierung neuer Benutzer."""

import logging

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    CoachProfile,
    Dashboard,
    Exercise,
    Plan,
    PlanDay,
    PlanExercise,
    PromptTemplate,
    Role,
    User,
    UserProfile,
    UserSettings,
)
from app.seed.exercises import seed_exercises
from app.seed.plans import PLANS
from app.seed.prompts import COACH_SYSTEM_PROMPT

log = logging.getLogger(__name__)

DEFAULT_WIDGETS = [
    {"id": "macros", "type": "macros", "w": 2, "h": 2, "visible": True, "config": {}},
    {"id": "workout", "type": "workout_today", "w": 2, "h": 1, "visible": True, "config": {}},
    {"id": "coach", "type": "coach_hint", "w": 2, "h": 1, "visible": True, "config": {}},
    {"id": "water", "type": "water", "w": 1, "h": 1, "visible": True, "config": {}},
    {"id": "streak", "type": "streak", "w": 1, "h": 1, "visible": True, "config": {}},
    {"id": "weight", "type": "weight_trend", "w": 2, "h": 2, "visible": True, "config": {"days": 30}},
    {"id": "heatmap", "type": "muscle_heatmap", "w": 2, "h": 2, "visible": True, "config": {"days": 7}},
]


async def seed_database(db: AsyncSession) -> None:
    count = (await db.exec(select(func.count()).select_from(Exercise).where(Exercise.owner_id.is_(None)))).one()
    if count == 0:
        for e in seed_exercises():
            db.add(Exercise(**e))
        await db.commit()
        log.info("Übungsbibliothek angelegt")

    tpl_count = (await db.exec(select(func.count()).select_from(Plan).where(Plan.is_template))).one()
    if tpl_count == 0:
        ex_map = {e.slug: e.id for e in (await db.exec(select(Exercise).where(Exercise.owner_id.is_(None)))).all()}
        for p in PLANS:
            plan = Plan(
                name=p["name"], description=p["description"], is_template=True, weeks=p["weeks"],
                deload_weeks=p["deload_weeks"], visibility="public",
            )
            db.add(plan)
            await db.flush()
            for pos, (day_name, weekday, items) in enumerate(p["days"]):
                day = PlanDay(plan_id=plan.id, name=day_name, position=pos, weekday=weekday)
                db.add(day)
                await db.flush()
                for i, (slug, sets, rmin, rmax, rpe, rest, ss) in enumerate(items):
                    db.add(
                        PlanExercise(
                            plan_day_id=day.id, exercise_id=ex_map[slug], position=i, sets=sets,
                            rep_min=rmin, rep_max=rmax, target_rpe=rpe, rest_seconds=rest, superset_group=ss,
                        )
                    )
        await db.commit()
        log.info("Planvorlagen angelegt")

    prompt = (await db.exec(select(PromptTemplate).where(PromptTemplate.name == "coach_system"))).first()
    if prompt is None:
        db.add(PromptTemplate(name="coach_system", version=1, content=COACH_SYSTEM_PROMPT, is_active=True,
                              comment="Standard"))
        await db.commit()

    if settings.admin_email and settings.admin_password:
        n = (await db.exec(select(func.count()).select_from(User))).one()
        if n == 0:
            admin = User(
                email=settings.admin_email.lower(), display_name="Admin",
                password_hash=hash_password(settings.admin_password), role=Role.admin,
            )
            db.add(admin)
            await db.commit()
            await db.refresh(admin)
            await init_user(db, admin)
            log.info("Admin-Benutzer %s angelegt", admin.email)


async def init_user(db: AsyncSession, user: User) -> None:
    if await db.get(UserSettings, user.id) is None:
        db.add(UserSettings(user_id=user.id, data={}))
    if await db.get(UserProfile, user.id) is None:
        db.add(UserProfile(user_id=user.id))
    if await db.get(CoachProfile, user.id) is None:
        db.add(CoachProfile(user_id=user.id))
    has_dash = (await db.exec(select(Dashboard).where(Dashboard.user_id == user.id))).first()
    if not has_dash:
        db.add(Dashboard(user_id=user.id, name="Heute", position=0, widgets=[dict(w) for w in DEFAULT_WIDGETS]))
    await db.commit()
