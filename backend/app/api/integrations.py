import json
import re
import datetime as dt
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import select

from app.core.deps import DB, CurrentUser
from app.models import BodyMeasurement, CardioSession, CoachHint, MetricDefinition, MetricEntry, Workout
from app.services import stats as st
from app.services.app_settings import get_user_settings
from app.services.cardio_import import KIND_ALIASES
from app.services.export import export_csv_zip, export_user, import_user
from app.services.meals import day_summary

router = APIRouter(tags=["integrations"])


# ================================================================ Home Assistant
@router.get("/ha/summary")
async def ha_summary(user: CurrentUser, db: DB) -> dict[str, Any]:
    """Für Home-Assistant-REST-Sensoren (Authorization: Bearer ff_…)."""
    s = await get_user_settings(db, user.id)
    today = date.today()
    day = await day_summary(db, user.id, today, s["meal_slots"])
    last = (await db.exec(select(Workout).where(Workout.user_id == user.id).order_by(Workout.started_at.desc()).limit(1))).first()
    weights = await st.weight_series(db, user.id, today - timedelta(days=14), today)
    hint = (await db.exec(select(CoachHint).where(CoachHint.user_id == user.id).order_by(CoachHint.created_at.desc()).limit(1))).first()
    trend = None
    if len(weights) >= 2:
        prev = next((w for w in reversed(weights) if (weights[-1]["day"] - w["day"]).days >= 7), weights[0])
        trend = round(weights[-1]["avg"] - prev["avg"], 2)
    streak = await st.streaks(db, user.id)
    return {
        "user": user.display_name,
        "kcal_today": round(day["totals"]["kcal"]),
        "kcal_target": round(day["targets"]["kcal"]),
        "kcal_remaining": round(day["targets"]["kcal"] - day["totals"]["kcal"]),
        "protein_today": round(day["totals"]["protein"]),
        "protein_target": round(day["targets"]["protein"]),
        "carbs_today": round(day["totals"]["carbs"]),
        "fat_today": round(day["totals"]["fat"]),
        "water_ml": day["water_ml"],
        "day_type": day["day_type"],
        "last_workout": last.name if last else None,
        "last_workout_at": last.started_at.isoformat() if last else None,
        "last_workout_days_ago": (today - st.local_date(last.started_at)).days if last else None,
        "weight_avg_7d": weights[-1]["avg"] if weights else None,
        "weight_trend_7d": trend,
        "streak_days": streak["days"],
        "last_hint_title": hint.title if hint else None,
        "last_hint": hint.body[:250] if hint else None,
        "updated": datetime.now(UTC).isoformat(),
    }


# ================================================================ Apple Health (Kurzbefehle)
class HealthWorkout(BaseModel):
    type: str = "run"
    start: datetime
    duration_min: float = 0
    distance_km: float | None = None
    kcal: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None


class HealthIn(BaseModel):
    date: dt.date | None = None
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    steps: float | None = None
    sleep_hours: float | None = None
    resting_hr: float | None = None
    active_kcal: float | None = None
    hrv_ms: float | None = None
    workouts: list[HealthWorkout] = []


HEALTH_METRICS = {
    "steps": ("Schritte", "number", ""),
    "sleep_hours": ("Schlaf", "number", "h"),
    "resting_hr": ("Ruhepuls", "number", "bpm"),
    "active_kcal": ("Aktive Energie", "number", "kcal"),
    "hrv_ms": ("HRV", "number", "ms"),
}


def _num(v: Any) -> float | None:
    if v in (None, ""):
        return None
    txt = str(v).strip().split()[0] if str(v).strip() else ""
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", txt):  # deutsches Tausendertrennzeichen: 10.000,5
        txt = txt.replace(".", "")
    try:
        return float(txt.replace(",", "."))
    except ValueError:
        return None


@router.post("/integrations/apple-health")
async def apple_health(body: HealthIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    """Aufruf aus einer iOS-Kurzbefehle-Automation. Mehrfaches Senden am selben Tag aktualisiert die Werte."""
    day = body.date or date.today()
    result: dict[str, Any] = {"day": day}
    if body.weight_kg or body.body_fat_pct:
        m = (await db.exec(select(BodyMeasurement).where(BodyMeasurement.user_id == user.id, BodyMeasurement.day == day,
                                                         BodyMeasurement.source == "health"))).first()
        m = m or BodyMeasurement(user_id=user.id, day=day, source="health")
        if body.weight_kg and 20 < body.weight_kg < 400:
            m.weight_kg = round(body.weight_kg, 2)
        if body.body_fat_pct:
            m.body_fat_pct = round(body.body_fat_pct * 100 if body.body_fat_pct < 1 else body.body_fat_pct, 1)
        db.add(m)
        result["body"] = True
    for field, (name, kind, unit) in HEALTH_METRICS.items():
        v = getattr(body, field)
        if v is None:
            continue
        md = (await db.exec(select(MetricDefinition).where(MetricDefinition.user_id == user.id, MetricDefinition.name == name))).first()
        if not md:
            md = MetricDefinition(user_id=user.id, name=name, kind=kind, unit=unit, scale_min=None, scale_max=None,
                                  chart="bar" if field in ("steps", "active_kcal") else "line")
            db.add(md)
            await db.flush()
        e = (await db.exec(select(MetricEntry).where(MetricEntry.metric_id == md.id, MetricEntry.day == day))).first()
        e = e or MetricEntry(user_id=user.id, metric_id=md.id, day=day)
        e.value_num = round(float(v), 2)
        db.add(e)
        result[field] = e.value_num
    added = 0
    for w in body.workouts:
        start = w.start if w.start.tzinfo else w.start.replace(tzinfo=UTC)
        kind = KIND_ALIASES.get(w.type.lower().strip(), "other")
        dup = (await db.exec(select(CardioSession.id).where(
            CardioSession.user_id == user.id, CardioSession.started_at >= start - timedelta(minutes=2),
            CardioSession.started_at <= start + timedelta(minutes=2)))).first()
        if dup:
            continue
        db.add(CardioSession(user_id=user.id, kind=kind, started_at=start, duration_s=int(w.duration_min * 60),
                             distance_m=w.distance_km * 1000 if w.distance_km else None, kcal=w.kcal, avg_hr=w.avg_hr,
                             max_hr=w.max_hr, source="health"))
        added += 1
    result["workouts_added"] = added
    await db.commit()
    return result


@router.post("/integrations/apple-health/raw")
async def apple_health_raw(payload: dict[str, Any], user: CurrentUser, db: DB) -> dict[str, Any]:
    """Tolerante Variante: Kurzbefehle liefern Zahlen oft als Text mit Einheit („80,4 kg“)."""
    data = {k: _num(v) for k, v in payload.items() if k in HealthIn.model_fields and k not in ("date", "workouts")}
    if payload.get("date"):
        data["date"] = str(payload["date"])[:10]
    return await apple_health(HealthIn(**data), user, db)


# ================================================================ Export / Import
@router.get("/me/export")
async def export(user: CurrentUser, db: DB, format: str = "json") -> Response:
    data = await export_user(db, user)
    stamp = date.today().isoformat()
    if format == "csv":
        return Response(export_csv_zip(data), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="fitforge-{stamp}.zip"'})
    return Response(json.dumps(data, ensure_ascii=False, indent=1, default=str), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="fitforge-{stamp}.json"'})


@router.post("/me/import")
async def import_data(user: CurrentUser, db: DB, file: UploadFile = File(...)) -> dict[str, Any]:
    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(422, "Keine gültige JSON-Datei") from e
    try:
        return {"imported": await import_user(db, user, data)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
