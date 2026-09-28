"""Ausführung bestätigter Coach-Vorschläge (PendingAction)."""

from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import BodyMeasurement, CoachProfile, PendingAction, Plan, User, UserProfile, Workout, WorkoutSet
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
        from app.ai import plan_edit

        plan = await db.get(Plan, a["plan_id"])
        if not plan or plan.owner_id != user.id:
            raise HTTPException(404, "Plan nicht gefunden")
        await plan_edit.assert_fresh(plan, a.get("base"))
        await plan_edit.write_plan(db, plan, a["after"])
        result = {"plan_id": plan.id}

    elif pa.tool == "propose_new_plan":
        from app.ai import plan_edit

        plan = await plan_edit.create_plan(db, user, a["spec"])
        result = {"plan_id": plan.id, "activated": plan.is_active}

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
