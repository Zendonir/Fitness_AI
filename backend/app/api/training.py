from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import col, delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.access import get_owned, get_readable, get_writable, not_found, readable_clause
from app.core.deps import DB, CurrentUser, SubjectId
from app.models import (
    CardioSession,
    CoachHint,
    Exercise,
    Plan,
    PlanDay,
    PlanExercise,
    Role,
    User,
    Workout,
    WorkoutSet,
)
from app.seed.exercises import EQUIPMENT, MUSCLES
from app.services.cardio_import import parse_csv, parse_gpx
from app.services.progression import SetData, epley, merge_rule, suggest

router = APIRouter(tags=["training"])


# ================================================================ Übungen
class ExerciseIn(BaseModel):
    name: str
    category: str = "compound"
    equipment: str = "other"
    primary_muscles: list[str] = []
    secondary_muscles: list[str] = []
    instructions: str = ""
    media_id: str | None = Field(None, max_length=160, pattern=r"^[a-z0-9-]+/[a-z0-9-]+$")
    custom_fields: list[dict[str, Any]] = []
    progression: dict[str, Any] = {}


@router.get("/muscles")
async def muscles() -> dict[str, Any]:
    return {"muscles": MUSCLES, "equipment": EQUIPMENT}


@router.get("/exercises")
async def list_exercises(
    user: CurrentUser, db: DB, q: str | None = None, muscle: str | None = None, equipment: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(Exercise).where(readable_clause(Exercise, "exercise", user.id)).order_by(Exercise.name)
    if q:
        stmt = stmt.where(col(Exercise.name).ilike(f"%{q}%"))
    if equipment:
        stmt = stmt.where(Exercise.equipment == equipment)
    rows = (await db.exec(stmt)).all()
    if muscle:
        rows = [e for e in rows if muscle in e.primary_muscles or muscle in e.secondary_muscles]
    return [{**e.model_dump(), "own": e.owner_id == user.id} for e in rows]


@router.get("/exercises/{eid}")
async def get_exercise(eid: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    e = await get_readable(db, Exercise, "exercise", eid, user)
    return {**e.model_dump(), "own": e.owner_id == user.id}


@router.post("/exercises")
async def create_exercise(body: ExerciseIn, user: CurrentUser, db: DB, global_: bool = Query(False, alias="global")) -> dict[str, Any]:
    owner = None if (global_ and user.role == Role.admin) else user.id
    e = Exercise(**body.model_dump(), owner_id=owner, visibility="public" if owner is None else "private")
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return e.model_dump()


@router.patch("/exercises/{eid}")
async def update_exercise(eid: int, body: dict[str, Any], user: CurrentUser, db: DB) -> dict[str, Any]:
    e = await get_writable(db, Exercise, "exercise", eid, user)
    for k in ExerciseIn.model_fields:
        if k in body:
            setattr(e, k, body[k])
    db.add(e)
    await db.commit()
    return e.model_dump()


@router.delete("/exercises/{eid}")
async def delete_exercise(eid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    e = await get_writable(db, Exercise, "exercise", eid, user)
    used = (await db.exec(select(WorkoutSet.id).where(WorkoutSet.exercise_id == eid, WorkoutSet.user_id != user.id).limit(1))).first()
    if used:
        raise HTTPException(409, "Übung wird von anderen Benutzern verwendet – bitte Freigabe entfernen statt löschen")
    await db.delete(e)
    await db.commit()
    return {"ok": True}


async def exercise_history(
    db: AsyncSession, user_id: int, exercise_id: int, limit: int = 5, exclude_workout: int | None = None
) -> list[list[WorkoutSet]]:
    stmt = (
        select(WorkoutSet, Workout.started_at)
        .join(Workout, Workout.id == WorkoutSet.workout_id)
        .where(WorkoutSet.user_id == user_id, WorkoutSet.exercise_id == exercise_id, WorkoutSet.completed)
        .order_by(Workout.started_at.desc(), WorkoutSet.position)
    )
    if exclude_workout:
        stmt = stmt.where(WorkoutSet.workout_id != exclude_workout)
    sessions: dict[int, list[WorkoutSet]] = {}
    for s, _ in (await db.exec(stmt.limit(limit * 15))).all():
        sessions.setdefault(s.workout_id, []).append(s)
        if len(sessions) > limit:
            sessions.pop(s.workout_id)
            break
    return list(sessions.values())[:limit]


async def suggestion_for(
    db: AsyncSession, user_id: int, ex: Exercise, pe: PlanExercise | None = None, deload: bool = False,
    deload_factor: float = 0.6, exclude_workout: int | None = None,
) -> dict[str, Any]:
    hist = await exercise_history(db, user_id, ex.id, 3, exclude_workout)
    rule = merge_rule(ex.progression, pe.rep_min if pe else None, pe.rep_max if pe else None)
    sugg = suggest(
        [[SetData(s.reps, s.weight_kg, s.rpe, s.is_warmup) for s in sess] for sess in hist],
        rule, pe.sets if pe else 3, deload, deload_factor,
    )
    return sugg.as_dict()


@router.get("/exercises/{eid}/suggestion")
async def exercise_suggestion(eid: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    ex = await get_readable(db, Exercise, "exercise", eid, user)
    return await suggestion_for(db, user.id, ex)


# ================================================================ Pläne
class PlanExerciseIn(BaseModel):
    exercise_id: int
    sets: int = 3
    rep_min: int = 8
    rep_max: int = 12
    target_rpe: float | None = 8
    rest_seconds: int = 120
    superset_group: str | None = None
    notes: str = ""


class PlanDayIn(BaseModel):
    name: str
    weekday: int | None = None
    notes: str = ""
    exercises: list[PlanExerciseIn] = []


class PlanIn(BaseModel):
    name: str
    description: str = ""
    weeks: int = 4
    deload_weeks: list[int] = []
    deload_factor: float = Field(0.6, ge=0.2, le=1.0)
    days: list[PlanDayIn] = []


async def plan_full(db: AsyncSession, plan: Plan, user_id: int | None = None) -> dict[str, Any]:
    days = (await db.exec(select(PlanDay).where(PlanDay.plan_id == plan.id).order_by(PlanDay.position))).all()
    day_ids = [d.id for d in days]
    pes = (
        await db.exec(select(PlanExercise).where(col(PlanExercise.plan_day_id).in_(day_ids)).order_by(PlanExercise.position))
    ).all() if day_ids else []
    ex_ids = {p.exercise_id for p in pes}
    exs = {e.id: e for e in (await db.exec(select(Exercise).where(col(Exercise.id).in_(ex_ids)))).all()} if ex_ids else {}
    out = plan.model_dump()
    out["own"] = plan.owner_id == user_id
    out["days"] = []
    for d in days:
        items = []
        for p in pes:
            if p.plan_day_id != d.id:
                continue
            e = exs.get(p.exercise_id)
            items.append({**p.model_dump(), "exercise": {"id": e.id, "name": e.name, "primary_muscles": e.primary_muscles,
                                                         "equipment": e.equipment} if e else None})
        out["days"].append({**d.model_dump(), "exercises": items})
    return out


async def _write_days(db: AsyncSession, plan: Plan, days: list[PlanDayIn], user: User) -> None:
    old_days = (await db.exec(select(PlanDay).where(PlanDay.plan_id == plan.id))).all()
    for d in old_days:
        await db.exec(delete(PlanExercise).where(PlanExercise.plan_day_id == d.id))  # type: ignore[call-overload]
        await db.delete(d)
    await db.flush()
    for pos, d in enumerate(days):
        day = PlanDay(plan_id=plan.id, name=d.name, position=pos, weekday=d.weekday, notes=d.notes)
        db.add(day)
        await db.flush()
        for i, pe in enumerate(d.exercises):
            await get_readable(db, Exercise, "exercise", pe.exercise_id, user)
            db.add(PlanExercise(plan_day_id=day.id, position=i, **pe.model_dump()))


@router.get("/plans")
async def list_plans(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(Plan).where(readable_clause(Plan, "plan", user.id)).order_by(Plan.is_template.desc(), Plan.name))).all()
    out = []
    for p in rows:
        n_days = (await db.exec(select(func.count()).select_from(PlanDay).where(PlanDay.plan_id == p.id))).one()
        kind = "own" if p.owner_id == user.id else ("template" if p.owner_id is None else "shared")
        out.append({**p.model_dump(), "kind": kind, "days_count": n_days})
    return out


@router.get("/plans/{pid}")
async def get_plan(pid: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    plan = await get_readable(db, Plan, "plan", pid, user)
    return await plan_full(db, plan, user.id)


@router.post("/plans")
async def create_plan(body: PlanIn, user: CurrentUser, db: DB, global_: bool = Query(False, alias="global")) -> dict[str, Any]:
    is_global = global_ and user.role == Role.admin
    plan = Plan(
        owner_id=None if is_global else user.id, name=body.name, description=body.description, weeks=body.weeks,
        deload_weeks=body.deload_weeks, deload_factor=body.deload_factor, is_template=is_global,
        visibility="public" if is_global else "private",
    )
    db.add(plan)
    await db.flush()
    await _write_days(db, plan, body.days, user)
    await db.commit()
    return await plan_full(db, plan, user.id)


@router.put("/plans/{pid}")
async def update_plan(pid: int, body: PlanIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    plan = await get_writable(db, Plan, "plan", pid, user)
    for k in ("name", "description", "weeks", "deload_weeks", "deload_factor"):
        setattr(plan, k, getattr(body, k))
    plan.updated_at = datetime.now(UTC)
    db.add(plan)
    await _write_days(db, plan, body.days, user)
    await db.commit()
    return await plan_full(db, plan, user.id)


@router.delete("/plans/{pid}")
async def delete_plan(pid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    plan = await get_writable(db, Plan, "plan", pid, user)
    await db.delete(plan)
    await db.commit()
    return {"ok": True}


async def copy_plan(db: AsyncSession, pid: int, user: User, as_global: bool = False) -> Plan:
    src = await get_readable(db, Plan, "plan", pid, user)
    full = await plan_full(db, src)
    plan = Plan(
        owner_id=None if as_global else user.id, name=src.name if as_global else f"{src.name}",
        description=src.description, weeks=src.weeks, deload_weeks=list(src.deload_weeks),
        deload_factor=src.deload_factor, is_template=as_global, visibility="public" if as_global else "private",
    )
    db.add(plan)
    await db.flush()
    days = [
        PlanDayIn(name=d["name"], weekday=d["weekday"], notes=d["notes"], exercises=[
            PlanExerciseIn(**{k: e[k] for k in PlanExerciseIn.model_fields}) for e in d["exercises"]
        ])
        for d in full["days"]
    ]
    await _write_days(db, plan, days, user)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.post("/plans/{pid}/copy")
async def copy_plan_ep(pid: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    plan = await copy_plan(db, pid, user)
    return await plan_full(db, plan, user.id)


@router.post("/plans/{pid}/activate")
async def activate_plan(pid: int, user: CurrentUser, db: DB, start: date | None = None) -> dict[str, Any]:
    plan = await get_readable(db, Plan, "plan", pid, user)
    if plan.owner_id != user.id:
        plan = await copy_plan(db, pid, user)
    for p in (await db.exec(select(Plan).where(Plan.owner_id == user.id, Plan.is_active))).all():
        p.is_active = False
        db.add(p)
    plan.is_active = True
    plan.started_on = start or date.today()
    db.add(plan)
    await db.commit()
    return await plan_full(db, plan, user.id)


@router.post("/plans/{pid}/deactivate")
async def deactivate_plan(pid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    plan = await get_writable(db, Plan, "plan", pid, user)
    plan.is_active = False
    db.add(plan)
    await db.commit()
    return {"ok": True}


def plan_week(plan: Plan, today: date | None = None) -> tuple[int, bool]:
    today = today or date.today()
    start = plan.started_on or today
    week = ((today - start).days // 7) % max(plan.weeks, 1) + 1
    return week, week in (plan.deload_weeks or [])


async def next_plan_day(db: AsyncSession, user_id: int, today: date | None = None) -> dict[str, Any] | None:
    today = today or date.today()
    plan = (await db.exec(select(Plan).where(Plan.owner_id == user_id, Plan.is_active))).first()
    if not plan:
        return None
    days = (await db.exec(select(PlanDay).where(PlanDay.plan_id == plan.id).order_by(PlanDay.position))).all()
    if not days:
        return None
    week, deload = plan_week(plan, today)
    day_ids = [d.id for d in days]
    last = (
        await db.exec(
            select(Workout).where(Workout.user_id == user_id, col(Workout.plan_day_id).in_(day_ids))
            .order_by(Workout.started_at.desc()).limit(1)
        )
    ).first()
    done_today = False
    if last:
        started = last.started_at if last.started_at.tzinfo else last.started_at.replace(tzinfo=UTC)
        done_today = started.date() == today
    scheduled = [d for d in days if d.weekday is not None]
    if scheduled:
        todays = next((d for d in days if d.weekday == today.weekday()), None)
        rest_day = todays is None
        day = todays or next((d for d in sorted(scheduled, key=lambda d: (d.weekday - today.weekday()) % 7)), days[0])
    else:
        rest_day = False
        if last:
            idx = next((i for i, d in enumerate(days) if d.id == last.plan_day_id), -1)
            day = days[idx] if done_today else days[(idx + 1) % len(days)]
        else:
            day = days[0]
    return {"plan_id": plan.id, "plan_name": plan.name, "week": week, "weeks": plan.weeks, "deload": deload,
            "day": day.model_dump(), "rest_day": rest_day, "done_today": done_today}


@router.get("/training/today")
async def training_today(user: CurrentUser, db: DB) -> dict[str, Any]:
    info = await next_plan_day(db, user.id)
    if not info:
        return {"active_plan": False}
    plan = await db.get(Plan, info["plan_id"])
    pes = (await db.exec(select(PlanExercise).where(PlanExercise.plan_day_id == info["day"]["id"]).order_by(PlanExercise.position))).all()
    items = []
    for pe in pes:
        ex = await db.get(Exercise, pe.exercise_id)
        if ex:
            items.append({**pe.model_dump(), "exercise": {"id": ex.id, "name": ex.name},
                          "suggestion": await suggestion_for(db, user.id, ex, pe, info["deload"], plan.deload_factor)})
    return {"active_plan": True, **info, "exercises": items}


# ================================================================ Workouts
class SetIn(BaseModel):
    exercise_id: int
    reps: int = 0
    weight_kg: float = 0
    rpe: float | None = Field(None, ge=1, le=10)
    is_warmup: bool = False
    completed: bool = True
    superset_group: str | None = None
    custom: dict[str, Any] = {}
    position: int | None = None
    client_id: str | None = None


class WorkoutStartIn(BaseModel):
    plan_day_id: int | None = None
    name: str | None = None
    client_id: str | None = None
    started_at: datetime | None = None


class WorkoutIn(WorkoutStartIn):
    finished_at: datetime | None = None
    notes: str = ""
    rating: int | None = None
    sets: list[SetIn] = []


def _wo_out(w: Workout, sets: list[WorkoutSet] | None = None) -> dict[str, Any]:
    out = w.model_dump()
    if sets is not None:
        out["sets"] = [s.model_dump() for s in sorted(sets, key=lambda s: (s.position, s.id or 0))]
    return out


@router.get("/workouts")
async def list_workouts(subject: SubjectId, db: DB, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
    ws = (
        await db.exec(select(Workout).where(Workout.user_id == subject).order_by(Workout.started_at.desc()).offset(offset).limit(min(limit, 200)))
    ).all()
    out = []
    for w in ws:
        sets = (await db.exec(select(WorkoutSet).where(WorkoutSet.workout_id == w.id))).all()
        work = [s for s in sets if not s.is_warmup and s.completed]
        out.append({**w.model_dump(), "sets_count": len(work), "volume_kg": round(sum(s.reps * s.weight_kg for s in work), 1),
                    "exercises_count": len({s.exercise_id for s in work})})
    return out


@router.get("/workouts/{wid}")
async def get_workout(wid: int, subject: SubjectId, db: DB) -> dict[str, Any]:
    w = await get_owned(db, Workout, wid, subject)
    sets = (await db.exec(select(WorkoutSet).where(WorkoutSet.workout_id == w.id))).all()
    ex_ids = {s.exercise_id for s in sets}
    exs = {e.id: e.name for e in (await db.exec(select(Exercise).where(col(Exercise.id).in_(ex_ids)))).all()} if ex_ids else {}
    out = _wo_out(w, list(sets))
    for s in out["sets"]:
        s["exercise_name"] = exs.get(s["exercise_id"], "?")
    return out


async def _by_client_id(db: AsyncSession, model, user_id: int, client_id: str | None):
    if not client_id:
        return None
    return (await db.exec(select(model).where(model.user_id == user_id, model.client_id == client_id))).first()


@router.post("/workouts/start")
async def start_workout(body: WorkoutStartIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    if existing := await _by_client_id(db, Workout, user.id, body.client_id):
        return await live_payload(db, user, existing)
    name = body.name or "Freies Training"
    deload = False
    if body.plan_day_id:
        day = await db.get(PlanDay, body.plan_day_id)
        plan = await db.get(Plan, day.plan_id) if day else None
        if not day or not plan or plan.owner_id != user.id:
            raise not_found()
        name = body.name or day.name
        _, deload = plan_week(plan)
    w = Workout(user_id=user.id, plan_day_id=body.plan_day_id, name=name, is_deload=deload,
                client_id=body.client_id, started_at=body.started_at or datetime.now(UTC))
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return await live_payload(db, user, w)


async def live_payload(db: AsyncSession, user: User, w: Workout) -> dict[str, Any]:
    """Alles für den Live-Modus: geplante Übungen, Vorschläge, Vorwerte, bereits geloggte Sätze."""
    sets = (await db.exec(select(WorkoutSet).where(WorkoutSet.workout_id == w.id))).all()
    planned: list[dict[str, Any]] = []
    deload_factor = 0.6
    if w.plan_day_id:
        day = await db.get(PlanDay, w.plan_day_id)
        plan = await db.get(Plan, day.plan_id) if day else None
        deload_factor = plan.deload_factor if plan else 0.6
        pes = (await db.exec(select(PlanExercise).where(PlanExercise.plan_day_id == w.plan_day_id).order_by(PlanExercise.position))).all()
        for pe in pes:
            ex = await db.get(Exercise, pe.exercise_id)
            if ex:
                planned.append({**pe.model_dump(), "exercise": ex.model_dump(),
                                "suggestion": await suggestion_for(db, user.id, ex, pe, w.is_deload, deload_factor, w.id)})
    planned_ids = {p["exercise_id"] for p in planned}
    for eid in dict.fromkeys(s.exercise_id for s in sets):
        if eid not in planned_ids:
            ex = await db.get(Exercise, eid)
            if ex:
                planned.append({"exercise_id": eid, "exercise": ex.model_dump(), "sets": 3, "rep_min": 8, "rep_max": 12,
                                "rest_seconds": 120, "superset_group": None, "target_rpe": None, "notes": "",
                                "suggestion": await suggestion_for(db, user.id, ex, None, False, 0.6, w.id)})
    return {**_wo_out(w, list(sets)), "exercises": planned}


@router.get("/workouts/{wid}/live")
async def workout_live(wid: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    w = await get_owned(db, Workout, wid, user.id)
    return await live_payload(db, user, w)


@router.post("/workouts")
async def create_workout(body: WorkoutIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    """Komplettes Workout anlegen (Offline-Sync, Import)."""
    if existing := await _by_client_id(db, Workout, user.id, body.client_id):
        return _wo_out(existing)
    w = Workout(user_id=user.id, plan_day_id=None, name=body.name or "Training", client_id=body.client_id,
                started_at=body.started_at or datetime.now(UTC), finished_at=body.finished_at, notes=body.notes,
                rating=body.rating)
    db.add(w)
    await db.flush()
    for i, s in enumerate(body.sets):
        await get_readable(db, Exercise, "exercise", s.exercise_id, user)
        db.add(WorkoutSet(workout_id=w.id, user_id=user.id, **{**s.model_dump(exclude={"position"}), "position": s.position if s.position is not None else i}))
    await db.commit()
    return _wo_out(w)


class WorkoutPatch(BaseModel):
    name: str | None = None
    notes: str | None = None
    rating: int | None = Field(None, ge=1, le=5)
    started_at: datetime | None = None
    finished_at: datetime | None = None


@router.patch("/workouts/{wid}")
async def patch_workout(wid: int, body: WorkoutPatch, user: CurrentUser, db: DB) -> dict[str, Any]:
    w = await get_owned(db, Workout, wid, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    db.add(w)
    await db.commit()
    return _wo_out(w)


@router.delete("/workouts/{wid}")
async def delete_workout(wid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    w = await get_owned(db, Workout, wid, user.id)
    await db.exec(delete(WorkoutSet).where(WorkoutSet.workout_id == w.id))  # type: ignore[call-overload]
    await db.delete(w)
    await db.commit()
    return {"ok": True}


@router.post("/workouts/{wid}/sets")
async def add_set(wid: int, body: SetIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    w = await get_owned(db, Workout, wid, user.id)
    if existing := await _by_client_id(db, WorkoutSet, user.id, body.client_id):
        return existing.model_dump()
    await get_readable(db, Exercise, "exercise", body.exercise_id, user)
    pos = body.position
    if pos is None:
        pos = (await db.exec(select(func.count()).select_from(WorkoutSet).where(WorkoutSet.workout_id == w.id))).one()
    s = WorkoutSet(workout_id=w.id, user_id=user.id, **{**body.model_dump(exclude={"position"}), "position": pos})
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s.model_dump()


@router.patch("/sets/{sid}")
async def patch_set(sid: int, body: dict[str, Any], user: CurrentUser, db: DB) -> dict[str, Any]:
    s = await get_owned(db, WorkoutSet, sid, user.id)
    for k in ("reps", "weight_kg", "rpe", "is_warmup", "completed", "superset_group", "custom", "position"):
        if k in body:
            setattr(s, k, body[k])
    db.add(s)
    await db.commit()
    return s.model_dump()


@router.delete("/sets/{sid}")
async def delete_set(sid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    s = await get_owned(db, WorkoutSet, sid, user.id)
    await db.delete(s)
    await db.commit()
    return {"ok": True}


async def detect_prs(db: AsyncSession, user_id: int, w: Workout) -> list[dict[str, Any]]:
    sets = (await db.exec(select(WorkoutSet).where(WorkoutSet.workout_id == w.id, WorkoutSet.completed, ~col(WorkoutSet.is_warmup)))).all()
    prs = []
    for eid in {s.exercise_id for s in sets}:
        mine = [s for s in sets if s.exercise_id == eid and s.reps > 0 and s.weight_kg > 0]
        if not mine:
            continue
        prev = (
            await db.exec(
                select(WorkoutSet).join(Workout, Workout.id == WorkoutSet.workout_id)
                .where(WorkoutSet.user_id == user_id, WorkoutSet.exercise_id == eid, WorkoutSet.workout_id != w.id,
                       Workout.started_at < w.started_at, WorkoutSet.completed, ~col(WorkoutSet.is_warmup))
            )
        ).all()
        if not prev:
            continue
        best_prev_1rm = max(epley(s.weight_kg, s.reps) for s in prev)
        best_prev_w = max(s.weight_kg for s in prev)
        best = max(mine, key=lambda s: epley(s.weight_kg, s.reps))
        ex = await db.get(Exercise, eid)
        if epley(best.weight_kg, best.reps) > best_prev_1rm:
            prs.append({"exercise_id": eid, "exercise": ex.name if ex else "?", "type": "e1rm",
                        "value": epley(best.weight_kg, best.reps), "previous": best_prev_1rm,
                        "set": {"reps": best.reps, "weight_kg": best.weight_kg}})
        top = max(s.weight_kg for s in mine)
        if top > best_prev_w:
            prs.append({"exercise_id": eid, "exercise": ex.name if ex else "?", "type": "weight", "value": top,
                        "previous": best_prev_w})
    return prs


@router.post("/workouts/{wid}/finish")
async def finish_workout(wid: int, user: CurrentUser, db: DB, body: WorkoutPatch | None = None) -> dict[str, Any]:
    w = await get_owned(db, Workout, wid, user.id)
    if body:
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(w, k, v)
    w.finished_at = w.finished_at or datetime.now(UTC)
    db.add(w)
    await db.commit()
    prs = await detect_prs(db, user.id, w)
    if prs:
        from app.services.app_settings import get_user_settings

        s = await get_user_settings(db, user.id)
        if s["ai"]["proactive"].get("enabled") and s["ai"]["proactive"].get("new_pr"):
            names = ", ".join(sorted({p["exercise"] for p in prs}))
            db.add(CoachHint(user_id=user.id, kind="new_pr", title="Neuer Rekord! 🏆",
                             body=f"Stark! Neue Bestleistung bei: {names}.", data={"prs": prs, "workout_id": w.id},
                             dedupe_key=f"pr:{w.id}"))
            await db.commit()
    return {**_wo_out(w), "prs": prs}


# ================================================================ Ausdauer
class CardioIn(BaseModel):
    kind: str = "run"
    started_at: datetime | None = None
    duration_s: int = 0
    distance_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    kcal: float | None = None
    elevation_m: float | None = None
    notes: str = ""
    source: str = "manual"
    client_id: str | None = None


@router.get("/cardio")
async def list_cardio(subject: SubjectId, db: DB, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    rows = (
        await db.exec(select(CardioSession).where(CardioSession.user_id == subject).order_by(CardioSession.started_at.desc()).offset(offset).limit(min(limit, 500)))
    ).all()
    return [{**r.model_dump(exclude={"track"}), "has_track": bool(r.track)} for r in rows]


@router.get("/cardio/{cid}")
async def get_cardio(cid: int, subject: SubjectId, db: DB) -> dict[str, Any]:
    return (await get_owned(db, CardioSession, cid, subject)).model_dump()


@router.post("/cardio")
async def create_cardio(body: CardioIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    if existing := await _by_client_id(db, CardioSession, user.id, body.client_id):
        return existing.model_dump()
    data = body.model_dump()
    data["started_at"] = data["started_at"] or datetime.now(UTC)
    c = CardioSession(user_id=user.id, **data)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c.model_dump()


@router.patch("/cardio/{cid}")
async def patch_cardio(cid: int, body: dict[str, Any], user: CurrentUser, db: DB) -> dict[str, Any]:
    c = await get_owned(db, CardioSession, cid, user.id)
    for k in CardioIn.model_fields:
        if k in body and k != "client_id":
            setattr(c, k, body[k])
    db.add(c)
    await db.commit()
    return c.model_dump()


@router.delete("/cardio/{cid}")
async def delete_cardio(cid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    c = await get_owned(db, CardioSession, cid, user.id)
    await db.delete(c)
    await db.commit()
    return {"ok": True}


@router.post("/cardio/import")
async def import_cardio(user: CurrentUser, db: DB, file: UploadFile = File(...), kind: str | None = Form(None)) -> dict[str, Any]:
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "Datei zu groß (max. 20 MB)")
    name = (file.filename or "").lower()
    try:
        items = [parse_gpx(content, kind)] if name.endswith(".gpx") or content.lstrip()[:5] == b"<?xml" else parse_csv(content)
    except Exception as e:  # noqa: BLE001 - Parserfehler an den Benutzer melden
        raise HTTPException(422, f"Datei konnte nicht gelesen werden: {e}") from e
    created = []
    for it in items:
        # Duplikate (gleicher Start ±1 min, gleiche Art) überspringen
        st = it["started_at"]
        dup = (
            await db.exec(select(CardioSession.id).where(
                CardioSession.user_id == user.id, CardioSession.kind == it["kind"],
                CardioSession.started_at >= st - timedelta(minutes=1), CardioSession.started_at <= st + timedelta(minutes=1)))
        ).first()
        if dup:
            continue
        c = CardioSession(user_id=user.id, **it)
        db.add(c)
        created.append(c)
    await db.commit()
    return {"imported": len(created), "skipped": len(items) - len(created)}


@router.get("/training/recent-exercises")
async def recent_exercises(user: CurrentUser, db: DB, limit: int = 12) -> list[dict[str, Any]]:
    rows = (
        await db.exec(
            select(WorkoutSet.exercise_id, func.max(WorkoutSet.created_at).label("last"))
            .where(WorkoutSet.user_id == user.id).group_by(WorkoutSet.exercise_id)
            .order_by(func.max(WorkoutSet.created_at).desc()).limit(limit)
        )
    ).all()
    out = []
    for eid, _ in rows:
        e = await db.get(Exercise, eid)
        if e:
            out.append({"id": e.id, "name": e.name, "primary_muscles": e.primary_muscles})
    return out

