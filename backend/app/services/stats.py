"""Auswertungen für Diagramme, Dashboard, Berichte und den KI-Coach."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models import (
    NUTRIENT_KEYS,
    BodyMeasurement,
    CardioSession,
    Exercise,
    MealEntry,
    UserProfile,
    WaterEntry,
    Workout,
    WorkoutSet,
)
from app.services.nutrition import body_from_profile, compute_targets
from app.services.progression import epley

TZ = ZoneInfo(settings.tz)
SECONDARY_WEIGHT = 0.5
REP_BUCKETS = (1, 3, 5, 8, 10, 12, 15)


def local_date(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(TZ).date()


def day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (datetime.combine(start, time.min, TZ).astimezone(UTC),
            datetime.combine(end + timedelta(days=1), time.min, TZ).astimezone(UTC))


def period(start: date | None, end: date | None, days: int) -> tuple[date, date]:
    end = end or date.today()
    start = start or end - timedelta(days=days - 1)
    return start, end


async def _sets_in_range(db: AsyncSession, user_id: int, start: date, end: date) -> list[tuple[WorkoutSet, datetime]]:
    a, b = day_bounds(start, end)
    rows = (
        await db.exec(
            select(WorkoutSet, Workout.started_at).join(Workout, Workout.id == WorkoutSet.workout_id)
            .where(WorkoutSet.user_id == user_id, Workout.started_at >= a, Workout.started_at < b,
                   WorkoutSet.completed, ~col(WorkoutSet.is_warmup))
        )
    ).all()
    return list(rows)


async def _exercises(db: AsyncSession, ids: set[int]) -> dict[int, Exercise]:
    if not ids:
        return {}
    return {e.id: e for e in (await db.exec(select(Exercise).where(col(Exercise.id).in_(ids)))).all()}


# ---------------------------------------------------------------- Training
async def muscle_volume(db: AsyncSession, user_id: int, start: date, end: date) -> dict[str, Any]:
    rows = await _sets_in_range(db, user_id, start, end)
    exs = await _exercises(db, {s.exercise_id for s, _ in rows})
    sets: dict[str, float] = defaultdict(float)
    volume: dict[str, float] = defaultdict(float)
    for s, _ in rows:
        e = exs.get(s.exercise_id)
        if not e:
            continue
        for m in e.primary_muscles:
            sets[m] += 1
            volume[m] += s.reps * s.weight_kg
        for m in e.secondary_muscles:
            sets[m] += SECONDARY_WEIGHT
            volume[m] += s.reps * s.weight_kg * SECONDARY_WEIGHT
    days = (end - start).days + 1
    weekly = {m: round(v * 7 / days, 1) for m, v in sets.items()}
    return {"start": start, "end": end, "sets": {k: round(v, 1) for k, v in sets.items()},
            "volume_kg": {k: round(v) for k, v in volume.items()}, "weekly_sets": weekly}


async def exercise_progress(db: AsyncSession, user_id: int, exercise_id: int, start: date, end: date) -> dict[str, Any]:
    rows = await _sets_in_range(db, user_id, start, end)
    all_rows = [(s, t) for s, t in rows if s.exercise_id == exercise_id]
    # Bestwerte über die gesamte Historie für PR-Markierungen
    hist = (
        await db.exec(select(WorkoutSet, Workout.started_at).join(Workout, Workout.id == WorkoutSet.workout_id)
                      .where(WorkoutSet.user_id == user_id, WorkoutSet.exercise_id == exercise_id, WorkoutSet.completed,
                             ~col(WorkoutSet.is_warmup)).order_by(Workout.started_at))
    ).all()
    sessions: dict[int, dict[str, Any]] = {}
    best_so_far = 0.0
    pr_sessions: set[int] = set()
    for s, t in hist:
        e1 = epley(s.weight_kg, s.reps)
        if e1 > best_so_far + 0.01:
            if best_so_far > 0:
                pr_sessions.add(s.workout_id)
            best_so_far = e1
    for s, t in sorted(all_rows, key=lambda x: x[1]):
        sess = sessions.setdefault(s.workout_id, {"workout_id": s.workout_id, "day": local_date(t), "e1rm": 0.0,
                                                  "volume_kg": 0.0, "sets": 0, "best_set": None, "top_weight": 0.0})
        e1 = epley(s.weight_kg, s.reps)
        sess["volume_kg"] = round(sess["volume_kg"] + s.reps * s.weight_kg, 1)
        sess["sets"] += 1
        sess["top_weight"] = max(sess["top_weight"], s.weight_kg)
        if e1 >= sess["e1rm"]:
            sess["e1rm"] = e1
            sess["best_set"] = {"reps": s.reps, "weight_kg": s.weight_kg, "rpe": s.rpe}
    for sid, sess in sessions.items():
        sess["pr"] = sid in pr_sessions
    rep_records: dict[int, dict[str, Any]] = {}
    for s, t in hist:
        for b in REP_BUCKETS:
            if s.reps >= b and s.weight_kg > rep_records.get(b, {}).get("weight_kg", 0):
                rep_records[b] = {"reps": b, "weight_kg": s.weight_kg, "day": local_date(t)}
    best = max(hist, key=lambda x: epley(x[0].weight_kg, x[0].reps), default=None)
    return {
        "exercise_id": exercise_id,
        "sessions": list(sessions.values()),
        "best_e1rm": round(epley(best[0].weight_kg, best[0].reps), 1) if best else None,
        "best_e1rm_day": local_date(best[1]) if best else None,
        "rep_records": [rep_records[b] for b in REP_BUCKETS if b in rep_records],
        "total_sessions": len({s.workout_id for s, _ in hist}),
    }


async def training_calendar(db: AsyncSession, user_id: int, start: date, end: date) -> list[dict[str, Any]]:
    a, b = day_bounds(start, end)
    days: dict[date, dict[str, Any]] = {}
    for w in (await db.exec(select(Workout).where(Workout.user_id == user_id, Workout.started_at >= a, Workout.started_at < b))).all():
        d = days.setdefault(local_date(w.started_at), {"workouts": 0, "cardio": 0, "volume_kg": 0.0, "minutes": 0})
        d["workouts"] += 1
        if w.finished_at:
            d["minutes"] += int((w.finished_at - w.started_at).total_seconds() // 60)
    for s, t in await _sets_in_range(db, user_id, start, end):
        d = days.setdefault(local_date(t), {"workouts": 0, "cardio": 0, "volume_kg": 0.0, "minutes": 0})
        d["volume_kg"] = round(d["volume_kg"] + s.reps * s.weight_kg)
    for c in (await db.exec(select(CardioSession).where(CardioSession.user_id == user_id, CardioSession.started_at >= a,
                                                        CardioSession.started_at < b))).all():
        d = days.setdefault(local_date(c.started_at), {"workouts": 0, "cardio": 0, "volume_kg": 0.0, "minutes": 0})
        d["cardio"] += 1
        d["minutes"] += c.duration_s // 60
    return [{"day": k, **v} for k, v in sorted(days.items())]


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def weekly_volume(db: AsyncSession, user_id: int, weeks: int = 12, end: date | None = None) -> dict[str, Any]:
    end = end or date.today()
    start = week_start(end) - timedelta(weeks=weeks - 1)
    rows = await _sets_in_range(db, user_id, start, end)
    exs = await _exercises(db, {s.exercise_id for s, _ in rows})
    labels = [(start + timedelta(weeks=i)) for i in range(weeks)]
    series: dict[str, list[float]] = defaultdict(lambda: [0.0] * weeks)
    tonnage = [0.0] * weeks
    for s, t in rows:
        idx = (week_start(local_date(t)) - start).days // 7
        if not 0 <= idx < weeks or s.exercise_id not in exs:
            continue
        for m in exs[s.exercise_id].primary_muscles:
            series[m][idx] += 1
        tonnage[idx] += s.reps * s.weight_kg
    return {"weeks": labels, "sets_by_muscle": dict(series), "tonnage_kg": [round(x) for x in tonnage]}


async def streaks(db: AsyncSession, user_id: int) -> dict[str, int]:
    today = date.today()
    start = today - timedelta(days=400)
    logged: set[date] = set((await db.exec(select(MealEntry.day).where(MealEntry.user_id == user_id, MealEntry.day >= start))).all())
    cal = await training_calendar(db, user_id, start, today)
    trained = {d["day"] for d in cal}
    active = logged | trained
    streak = 0
    d = today if today in active else today - timedelta(days=1)
    while d in active:
        streak += 1
        d -= timedelta(days=1)
    week_streak = 0
    w = week_start(today)
    if not any(week_start(x) == w for x in trained):
        w -= timedelta(weeks=1)
    while any(week_start(x) == w for x in trained):
        week_streak += 1
        w -= timedelta(weeks=1)
    return {"days": streak, "training_weeks": week_streak, "workouts_30d": sum(1 for x in trained if (today - x).days < 30)}


# ---------------------------------------------------------------- Ernährung
async def nutrition_stats(db: AsyncSession, user_id: int, start: date, end: date) -> dict[str, Any]:
    entries = (await db.exec(select(MealEntry).where(MealEntry.user_id == user_id, MealEntry.day >= start, MealEntry.day <= end))).all()
    profile = await db.get(UserProfile, user_id) or UserProfile(user_id=user_id)
    targets_all = compute_targets(body_from_profile(profile), profile.custom_targets)
    cal = {d["day"] for d in await training_calendar(db, user_id, start, end)}
    days: dict[date, dict[str, float]] = {}
    micros: dict[str, float] = defaultdict(float)
    foods: dict[str, dict[str, float]] = {}
    for e in entries:
        d = days.setdefault(e.day, {k: 0.0 for k in NUTRIENT_KEYS})
        for k in NUTRIENT_KEYS:
            d[k] += getattr(e, k)
        for mk, mv in (e.micros or {}).items():
            micros[mk] += mv
        f = foods.setdefault(e.name, {"name": e.name, "kcal": 0.0, "protein": 0.0, "count": 0})
        f["kcal"] += e.kcal
        f["protein"] += e.protein
        f["count"] += 1
    water = defaultdict(int)
    for w in (await db.exec(select(WaterEntry).where(WaterEntry.user_id == user_id, WaterEntry.day >= start, WaterEntry.day <= end))).all():
        water[w.day] += w.ml
    series = []
    d = start
    while d <= end:
        t = targets_all["training" if d in cal else "rest"]
        vals = days.get(d)
        series.append({"day": d, "logged": vals is not None, **({k: round(v, 1) for k, v in vals.items()} if vals else {}),
                       "water_ml": water.get(d, 0), "target_kcal": t["kcal"], "target_protein": t["protein"],
                       "day_type": "training" if d in cal else "rest"})
        d += timedelta(days=1)
    logged = [s for s in series if s["logged"]]
    n = len(logged) or 1
    avg = {k: round(sum(s.get(k, 0) for s in logged) / n, 1) for k in NUTRIENT_KEYS}
    macro_kcal = avg["protein"] * 4 + avg["carbs"] * 4 + avg["fat"] * 9 or 1
    weekly: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for s in logged:
        weekly[week_start(s["day"])].append(s)
    return {
        "start": start, "end": end, "days": series, "average": avg, "logged_days": len(logged),
        "distribution_pct": {"protein": round(avg["protein"] * 4 / macro_kcal * 100), "carbs": round(avg["carbs"] * 4 / macro_kcal * 100),
                             "fat": round(avg["fat"] * 9 / macro_kcal * 100)},
        "weekly": [{"week": w, "kcal": round(sum(x["kcal"] for x in v) / len(v)), "protein": round(sum(x["protein"] for x in v) / len(v))}
                   for w, v in sorted(weekly.items())],
        "micros_avg": {k: round(v / n, 2) for k, v in micros.items()},
        "top_protein": sorted(foods.values(), key=lambda f: f["protein"], reverse=True)[:10],
        "top_kcal": sorted(foods.values(), key=lambda f: f["kcal"], reverse=True)[:10],
        "adherence_pct": round(sum(1 for s in logged if abs(s["kcal"] - s["target_kcal"]) <= s["target_kcal"] * 0.1) / n * 100),
        "protein_hit_pct": round(sum(1 for s in logged if s["protein"] >= s["target_protein"] * 0.95) / n * 100),
    }


# ---------------------------------------------------------------- Körper
async def weight_series(db: AsyncSession, user_id: int, start: date, end: date) -> list[dict[str, Any]]:
    from app.api.body import rolling_avg

    rows = (await db.exec(select(BodyMeasurement).where(BodyMeasurement.user_id == user_id, BodyMeasurement.day >= start - timedelta(days=7),
                                                        BodyMeasurement.day <= end, col(BodyMeasurement.weight_kg).is_not(None))
                          .order_by(BodyMeasurement.day, BodyMeasurement.created_at))).all()
    w = {r.day: r.weight_kg for r in rows}
    return [p for p in rolling_avg(sorted(w.items())) if p["day"] >= start]


# ---------------------------------------------------------------- Korrelationen
async def correlations(db: AsyncSession, user_id: int, start: date, end: date) -> dict[str, Any]:
    nut = await nutrition_stats(db, user_id, start, end)
    weights = await weight_series(db, user_id, start, end)
    profile = await db.get(UserProfile, user_id) or UserProfile(user_id=user_id)
    tdee = compute_targets(body_from_profile(profile))["tdee"]
    wmap = {p["day"]: p["avg"] for p in weights}
    weekly = []
    for wk in sorted({week_start(s["day"]) for s in nut["days"]}):
        days = [s for s in nut["days"] if week_start(s["day"]) == wk and s["logged"]]
        wk_weights = [wmap[d] for d in sorted(wmap) if week_start(d) == wk]
        weekly.append({
            "week": wk,
            "kcal_balance": round(sum(s["kcal"] - tdee for s in days) / len(days)) if days else None,
            "protein_avg": round(sum(s["protein"] for s in days) / len(days)) if days else None,
            "weight_avg": round(sum(wk_weights) / len(wk_weights), 2) if wk_weights else None,
        })
    for i, w in enumerate(weekly):
        prev = weekly[i - 1]["weight_avg"] if i else None
        w["weight_change"] = round(w["weight_avg"] - prev, 2) if w["weight_avg"] is not None and prev is not None else None
    # Kraft: Summe der besten e1RM je Übung pro Woche relativ zur ersten Woche (Index 100)
    rows = await _sets_in_range(db, user_id, start, end)
    best: dict[tuple[date, int], float] = {}
    for s, t in rows:
        k = (week_start(local_date(t)), s.exercise_id)
        best[k] = max(best.get(k, 0), epley(s.weight_kg, s.reps))
    first: dict[int, float] = {}
    strength: dict[date, list[float]] = defaultdict(list)
    for (wk, eid), v in sorted(best.items()):
        first.setdefault(eid, v)
        if first[eid] > 0:
            strength[wk].append(v / first[eid] * 100)
    for w in weekly:
        vals = strength.get(w["week"])
        w["strength_index"] = round(sum(vals) / len(vals), 1) if vals else None
    pairs = [(w["kcal_balance"], w["weight_change"]) for w in weekly if w["kcal_balance"] is not None and w["weight_change"] is not None]
    pairs2 = [(w["protein_avg"], w["strength_index"]) for w in weekly if w["protein_avg"] is not None and w["strength_index"] is not None]
    return {"tdee": tdee, "weekly": weekly, "r_balance_weight": pearson(pairs), "r_protein_strength": pearson(pairs2)}


def pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs, strict=True)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    return round(cov / (vx * vy), 2) if vx and vy else None


# ---------------------------------------------------------------- Zusammenfassung (Berichte / KI-Kontext)
async def period_summary(db: AsyncSession, user_id: int, start: date, end: date) -> dict[str, Any]:
    a, b = day_bounds(start, end)
    workouts = (await db.exec(select(Workout).where(Workout.user_id == user_id, Workout.started_at >= a, Workout.started_at < b)
                              .order_by(Workout.started_at))).all()
    rows = await _sets_in_range(db, user_id, start, end)
    exs = await _exercises(db, {s.exercise_id for s, _ in rows})
    cardio = (await db.exec(select(CardioSession).where(CardioSession.user_id == user_id, CardioSession.started_at >= a,
                                                        CardioSession.started_at < b))).all()
    nut = await nutrition_stats(db, user_id, start, end)
    weights = await weight_series(db, user_id, start, end)
    mv = await muscle_volume(db, user_id, start, end)
    rpes = [s.rpe for s, _ in rows if s.rpe]
    prs = []
    for w in workouts:
        from app.api.training import detect_prs

        prs += [{**p, "day": local_date(w.started_at)} for p in await detect_prs(db, user_id, w)]
    by_ex: dict[str, dict[str, Any]] = {}
    for s, _ in rows:
        name = exs[s.exercise_id].name if s.exercise_id in exs else "?"
        e = by_ex.setdefault(name, {"sets": 0, "best_e1rm": 0.0, "volume_kg": 0.0})
        e["sets"] += 1
        e["best_e1rm"] = max(e["best_e1rm"], epley(s.weight_kg, s.reps))
        e["volume_kg"] = round(e["volume_kg"] + s.reps * s.weight_kg)
    return {
        "start": start, "end": end,
        "training": {
            "workouts": len(workouts), "sets": len(rows), "tonnage_kg": round(sum(s.reps * s.weight_kg for s, _ in rows)),
            "avg_rpe": round(sum(rpes) / len(rpes), 1) if rpes else None,
            "workout_list": [{"day": local_date(w.started_at), "name": w.name, "rating": w.rating} for w in workouts],
            "exercises": by_ex, "muscle_sets": mv["sets"], "prs": prs,
        },
        "cardio": {"sessions": len(cardio), "minutes": sum(c.duration_s for c in cardio) // 60,
                   "distance_km": round(sum(c.distance_m or 0 for c in cardio) / 1000, 1)},
        "nutrition": {k: nut[k] for k in ("average", "logged_days", "adherence_pct", "protein_hit_pct", "distribution_pct")}
        | {"target_kcal_avg": round(sum(d["target_kcal"] for d in nut["days"]) / max(len(nut["days"]), 1)),
           "target_protein_avg": round(sum(d["target_protein"] for d in nut["days"]) / max(len(nut["days"]), 1))},
        "body": {"weight_start": weights[0]["avg"] if weights else None, "weight_end": weights[-1]["avg"] if weights else None,
                 "weight_change": round(weights[-1]["avg"] - weights[0]["avg"], 2) if len(weights) > 1 else None},
    }
