"""Ausführung bestätigter Coach-Vorschläge (PendingAction)."""

from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import BodyMeasurement, CoachProfile, PendingAction, Plan, PlanDay, PlanExercise, User, UserProfile, Workout, WorkoutSet
from app.services.meals import build_meal_entry


async def execute_action(db: AsyncSession, user: User, pa: PendingAction) -> dict[str, Any]:
    if pa.user_id != user.id:
        raise HTTPException(404, "Nicht gefunden")
    if pa.status != "pending":
        raise HTTPException(409, "Aktion wurde bereits bearbeitet")
    a = pa.args
    result: dict[str, Any] = {}

    if pa.tool == "propose_log_meal":
        day = date.fromisoformat(a["day"]) if a.get("day") else date.today()
        ids = []
        for it in a.get("items", []):
            e = await build_meal_entry(db, user, {**it, "day": day, "slot": a.get("slot") or "Snacks", "source": "coach"})
            db.add(e)
            await db.flush()
            ids.append(e.id)
        result = {"meal_entry_ids": ids}

    elif pa.tool == "propose_nutrition_goal":
        p = await db.get(UserProfile, user.id) or UserProfile(user_id=user.id)
        p.goal = a.get("goal") or p.goal
        if a.get("custom"):
            p.custom_targets = a["custom"]
        db.add(p)
        result = {"goal": p.goal}

    elif pa.tool == "propose_plan_changes":
        plan = await db.get(Plan, a["plan_id"])
        if not plan or plan.owner_id != user.id:
            raise HTTPException(404, "Plan nicht gefunden")
        from app.ai.tools import ToolContext, find_exercise

        ctx = ToolContext(db=db, user=user)
        days = (await db.exec(select(PlanDay).where(PlanDay.plan_id == plan.id))).all()
        by_name = {d.name.lower(): d for d in days}
        for d in a["days"]:
            day = by_name.get(d["day"].lower())
            if not day:
                continue
            for old in (await db.exec(select(PlanExercise).where(PlanExercise.plan_day_id == day.id))).all():
                await db.delete(old)
            await db.flush()
            for i, e in enumerate(d["exercises"]):
                ex = await find_exercise(ctx, e["exercise"])
                if ex:
                    db.add(PlanExercise(plan_day_id=day.id, exercise_id=ex.id, position=i, sets=e.get("sets", 3),
                                        rep_min=e.get("rep_min", 8), rep_max=e.get("rep_max", 12),
                                        rest_seconds=e.get("rest_seconds", 120), target_rpe=e.get("target_rpe")))
        plan.updated_at = datetime.now(UTC)
        db.add(plan)
        result = {"plan_id": plan.id}

    elif pa.tool == "propose_workout":
        w = Workout(user_id=user.id, name=a.get("name") or "Coach-Workout")
        db.add(w)
        await db.flush()
        pos = 0
        for e in a.get("exercises", []):
            for _ in range(int(e.get("sets", 3))):
                db.add(WorkoutSet(workout_id=w.id, user_id=user.id, exercise_id=e["exercise_id"], position=pos,
                                  reps=int(e.get("reps", 10)), weight_kg=float(e.get("weight_kg", 0)), completed=False))
                pos += 1
        result = {"workout_id": w.id}

    elif pa.tool == "propose_log_weight":
        m = BodyMeasurement(user_id=user.id, day=date.fromisoformat(a["day"]), weight_kg=float(a["weight_kg"]), source="coach")
        db.add(m)
        result = {"weight_kg": m.weight_kg}

    elif pa.tool == "propose_profile_update":
        cp = await db.get(CoachProfile, user.id) or CoachProfile(user_id=user.id)
        setattr(cp, a["field"], a["value"])
        cp.updated_at = datetime.now(UTC)
        db.add(cp)
        result = {"field": a["field"]}
    else:
        raise HTTPException(400, "Unbekannte Aktion")

    pa.status = "confirmed"
    pa.result = result
    pa.resolved_at = datetime.now(UTC)
    db.add(pa)
    await db.commit()
    return result
