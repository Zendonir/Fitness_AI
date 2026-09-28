"""Plan-Bearbeitung durch den KI-Coach.

Ablauf: Snapshot des Plans → Operationen anwenden (nur im Speicher) → Vorschlag mit Vorher/Nachher speichern →
nach Bestätigung wird der Nachher-Stand in die Datenbank geschrieben. Übungen werden bereits beim Vorschlag
aufgelöst (exercise_id), damit beim Übernehmen nichts mehr „geraten“ werden muss.
"""

import copy
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Exercise, Plan, PlanDay, PlanExercise, User

WEEKDAYS = {
    "mo": 0, "montag": 0, "di": 1, "dienstag": 1, "mi": 2, "mittwoch": 2, "do": 3, "donnerstag": 3,
    "fr": 4, "freitag": 4, "sa": 5, "samstag": 5, "so": 6, "sonntag": 6,
    "mon": 0, "monday": 0, "tue": 1, "tuesday": 1, "wed": 2, "wednesday": 2, "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}
EX_FIELDS = ("sets", "rep_min", "rep_max", "target_rpe", "rest_seconds", "superset_group", "notes")
LIMITS = {"sets": (1, 12), "rep_min": (1, 100), "rep_max": (1, 100), "rest_seconds": (0, 900), "target_rpe": (5, 10)}


def parse_weekday(v: Any) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, int | float):
        return int(v) if 0 <= int(v) <= 6 else None
    return WEEKDAYS.get(str(v).strip().lower().rstrip("."))


def stamp(plan: Plan) -> str:
    return plan.updated_at.isoformat() if plan.updated_at else ""


async def snapshot(db: AsyncSession, plan: Plan) -> dict[str, Any]:
    days = (await db.exec(select(PlanDay).where(PlanDay.plan_id == plan.id).order_by(PlanDay.position))).all()
    out_days = []
    for d in days:
        pes = (await db.exec(select(PlanExercise).where(PlanExercise.plan_day_id == d.id).order_by(PlanExercise.position))).all()
        items = []
        for p in pes:
            e = await db.get(Exercise, p.exercise_id)
            items.append({"exercise_id": p.exercise_id, "exercise": e.name if e else "?", "sets": p.sets, "rep_min": p.rep_min,
                          "rep_max": p.rep_max, "target_rpe": p.target_rpe, "rest_seconds": p.rest_seconds,
                          "superset_group": p.superset_group, "notes": p.notes or ""})
        out_days.append({"id": d.id, "day": d.name, "weekday": d.weekday, "notes": d.notes or "", "exercises": items})
    return {"id": plan.id, "name": plan.name, "description": plan.description, "weeks": plan.weeks,
            "deload_weeks": list(plan.deload_weeks or []), "deload_factor": plan.deload_factor, "days": out_days}


def _clean_fields(ch: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in EX_FIELDS:
        if k not in ch or ch[k] is None:
            continue
        v = ch[k]
        if k in LIMITS:
            lo, hi = LIMITS[k]
            v = float(v) if k == "target_rpe" else int(v)
            v = min(max(v, lo), hi)
        elif k == "superset_group":
            v = str(v).strip()[:2] or None
        else:
            v = str(v)[:300]
        out[k] = v
    if "rep_min" in out and "rep_max" in out and out["rep_min"] > out["rep_max"]:
        out["rep_min"], out["rep_max"] = out["rep_max"], out["rep_min"]
    return out


def _find_day(days: list[dict[str, Any]], name: Any) -> dict[str, Any] | None:
    key = str(name or "").strip().lower()
    if not key:
        return None
    for d in days:
        if d["day"].lower() == key:
            return d
    matches = [d for d in days if key in d["day"].lower()]
    if len(matches) == 1:
        return matches[0]
    if key.isdigit() and 1 <= int(key) <= len(days):
        return days[int(key) - 1]
    return None


def _find_ex(day: dict[str, Any], name: Any) -> int | None:
    key = str(name or "").strip().lower()
    for i, e in enumerate(day["exercises"]):
        if e["exercise"].lower() == key:
            return i
    matches = [i for i, e in enumerate(day["exercises"]) if key and key in e["exercise"].lower()]
    return matches[0] if len(matches) == 1 else None


def _pos(v: Any, length: int) -> int:
    try:
        p = int(v) - 1  # 1-basiert für das Modell
    except (TypeError, ValueError):
        return length
    return min(max(p, 0), length)


async def apply_changes(before: dict[str, Any], changes: list[dict[str, Any]], resolve) -> tuple[dict[str, Any], list[str]]:
    """Wendet Operationen auf eine Kopie an. resolve(name) -> Exercise | None."""
    after = copy.deepcopy(before)
    warnings: list[str] = []
    days = after["days"]
    for ch in changes:
        op = ch.get("op")
        if op == "set_plan":
            if ch.get("name"):
                after["name"] = str(ch["name"])[:120]
            if ch.get("weeks"):
                after["weeks"] = min(max(int(ch["weeks"]), 1), 52)
            if ch.get("deload_weeks") is not None:
                after["deload_weeks"] = sorted({int(w) for w in ch["deload_weeks"] if 1 <= int(w) <= after["weeks"]})
            if ch.get("deload_factor"):
                after["deload_factor"] = min(max(float(ch["deload_factor"]), 0.2), 1.0)
            continue
        if op == "add_day":
            name = str(ch.get("new_name") or ch.get("day") or f"Tag {len(days) + 1}")[:80]
            if _find_day(days, name) and _find_day(days, name)["day"].lower() == name.lower():
                warnings.append(f"Tag „{name}“ existiert bereits")
                continue
            days.insert(_pos(ch.get("position"), len(days)), {"id": None, "day": name, "weekday": parse_weekday(ch.get("weekday")),
                                                                "notes": "", "exercises": []})
            continue
        day = _find_day(days, ch.get("day"))
        if not day:
            warnings.append(f"Tag „{ch.get('day')}“ nicht gefunden")
            continue
        if op == "remove_day":
            days.remove(day)
        elif op == "rename_day":
            day["day"] = str(ch.get("new_name") or day["day"])[:80]
        elif op == "set_weekday":
            day["weekday"] = parse_weekday(ch.get("weekday"))
        elif op == "move_day":
            days.remove(day)
            days.insert(_pos(ch.get("position"), len(days)), day)
        elif op in ("add", "replace"):
            ex = await resolve(str(ch.get("new_exercise") or ""))
            if not ex:
                warnings.append(f"Übung „{ch.get('new_exercise')}“ nicht gefunden")
                continue
            fields = _clean_fields(ch)
            if op == "add":
                prog = ex.progression or {}
                item = {"exercise_id": ex.id, "exercise": ex.name, "sets": 3, "rep_min": prog.get("rep_min", 8),
                        "rep_max": prog.get("rep_max", 12), "target_rpe": 8.0, "rest_seconds": 120, "superset_group": None,
                        "notes": "", **fields}
                day["exercises"].insert(_pos(ch.get("position"), len(day["exercises"])), item)
            else:
                idx = _find_ex(day, ch.get("exercise"))
                if idx is None:
                    warnings.append(f"„{ch.get('exercise')}“ an „{day['day']}“ nicht gefunden")
                    continue
                day["exercises"][idx] = {**day["exercises"][idx], "exercise_id": ex.id, "exercise": ex.name, **fields}
        elif op in ("remove", "update", "move"):
            idx = _find_ex(day, ch.get("exercise"))
            if idx is None:
                warnings.append(f"„{ch.get('exercise')}“ an „{day['day']}“ nicht gefunden")
                continue
            if op == "remove":
                day["exercises"].pop(idx)
            elif op == "update":
                day["exercises"][idx].update(_clean_fields(ch))
            else:
                item = day["exercises"].pop(idx)
                day["exercises"].insert(_pos(ch.get("position"), len(day["exercises"])), item)
        else:
            warnings.append(f"Unbekannte Operation „{op}“")
    after["deload_weeks"] = [w for w in after["deload_weeks"] if w <= after["weeks"]]
    before_dupes = {(d.get("id"), e["exercise_id"]) for d in before["days"]
                    for e in d["exercises"] if [x["exercise_id"] for x in d["exercises"]].count(e["exercise_id"]) > 1}
    for d in days:
        ids = [e["exercise_id"] for e in d["exercises"]]
        for e in d["exercises"]:
            if ids.count(e["exercise_id"]) > 1 and (d.get("id"), e["exercise_id"]) not in before_dupes:
                msg = f"„{e['exercise']}“ kommt an „{d['day']}“ mehrfach vor"
                if msg not in warnings:
                    warnings.append(msg)
    return after, warnings


async def write_plan(db: AsyncSession, plan: Plan, after: dict[str, Any]) -> None:
    """Schreibt den Nachher-Stand. Bestehende Tage (per ID) bleiben erhalten → Workout-Verlauf bleibt verknüpft."""
    plan.name = after.get("name") or plan.name
    plan.weeks = after.get("weeks", plan.weeks)
    plan.deload_weeks = after.get("deload_weeks", plan.deload_weeks)
    plan.deload_factor = after.get("deload_factor", plan.deload_factor)
    plan.updated_at = datetime.now(UTC)
    db.add(plan)
    existing = {d.id: d for d in (await db.exec(select(PlanDay).where(PlanDay.plan_id == plan.id))).all()}
    keep: set[int] = set()
    for pos, d in enumerate(after["days"]):
        day = existing.get(d.get("id")) if d.get("id") else None
        if day is None:
            day = PlanDay(plan_id=plan.id, name=d["day"], position=pos)
        day.name, day.position, day.weekday, day.notes = d["day"], pos, d.get("weekday"), d.get("notes", "")
        db.add(day)
        await db.flush()
        keep.add(day.id)
        for old in (await db.exec(select(PlanExercise).where(PlanExercise.plan_day_id == day.id))).all():
            await db.delete(old)
        await db.flush()
        for i, e in enumerate(d["exercises"]):
            db.add(PlanExercise(plan_day_id=day.id, exercise_id=e["exercise_id"], position=i, sets=e.get("sets", 3),
                                rep_min=e.get("rep_min", 8), rep_max=e.get("rep_max", 12), target_rpe=e.get("target_rpe"),
                                rest_seconds=e.get("rest_seconds", 120), superset_group=e.get("superset_group"),
                                notes=e.get("notes") or ""))
    for did, day in existing.items():
        if did not in keep:
            await db.delete(day)


async def create_plan(db: AsyncSession, user: User, spec: dict[str, Any]) -> Plan:
    plan = Plan(owner_id=user.id, name=spec["name"], description=spec.get("description", ""), weeks=spec.get("weeks", 4),
                deload_weeks=spec.get("deload_weeks", []), deload_factor=spec.get("deload_factor", 0.6))
    db.add(plan)
    await db.flush()
    await write_plan(db, plan, spec)
    if spec.get("activate"):
        for p in (await db.exec(select(Plan).where(Plan.owner_id == user.id, Plan.is_active, Plan.id != plan.id))).all():
            p.is_active = False
            db.add(p)
        plan.is_active = True
        plan.started_on = date.today()
        db.add(plan)
    return plan


async def assert_fresh(plan: Plan, expected: str | None) -> None:
    if expected and stamp(plan) != expected:
        raise HTTPException(409, "Der Plan wurde seit dem Vorschlag geändert – bitte den Coach erneut fragen.")
