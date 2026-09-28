from datetime import date, datetime, time, timedelta
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import BodyMeasurement, Plan, PlanDay, UserProfile, Workout
from app.services.nutrition import body_from_profile, compute_targets


async def latest_weight(db: AsyncSession, user_id: int) -> float | None:
    row = (
        await db.exec(
            select(BodyMeasurement)
            .where(BodyMeasurement.user_id == user_id, BodyMeasurement.weight_kg.is_not(None))
            .order_by(BodyMeasurement.day.desc())
            .limit(1)
        )
    ).first()
    return row.weight_kg if row else None


async def is_training_day(db: AsyncSession, user_id: int, day: date) -> bool:
    start = datetime.combine(day, time.min)
    wo = (
        await db.exec(
            select(Workout.id).where(
                Workout.user_id == user_id, Workout.started_at >= start, Workout.started_at < start + timedelta(days=1)
            )
        )
    ).first()
    if wo:
        return True
    plan = (await db.exec(select(Plan).where(Plan.owner_id == user_id, Plan.is_active))).first()
    if plan:
        pd = (
            await db.exec(select(PlanDay.id).where(PlanDay.plan_id == plan.id, PlanDay.weekday == day.weekday()))
        ).first()
        return pd is not None
    return False


async def user_targets(db: AsyncSession, user_id: int, day: date | None = None) -> dict[str, Any]:
    day = day or date.today()
    profile = await db.get(UserProfile, user_id) or UserProfile(user_id=user_id)
    body = body_from_profile(profile, await latest_weight(db, user_id))
    all_t = compute_targets(body, profile.custom_targets)
    training = await is_training_day(db, user_id, day)
    return {**all_t, "day_type": "training" if training else "rest", "today": all_t["training" if training else "rest"]}
