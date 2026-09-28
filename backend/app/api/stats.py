from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from app.core.access import get_owned, get_readable
from app.core.deps import DB, CurrentUser, SubjectId
from app.models import CoachHint, CoachSummary, Dashboard, Exercise
from app.services import stats as st
from app.services.app_settings import get_user_settings
from app.services.meals import day_summary

router = APIRouter(tags=["stats"])


@router.get("/stats/muscles")
async def muscles(subject: SubjectId, db: DB, days: int = 7, start: date | None = None, end: date | None = None) -> dict[str, Any]:
    s, e = st.period(start, end, days)
    return await st.muscle_volume(db, subject, s, e)


@router.get("/stats/exercise/{eid}")
async def exercise(eid: int, subject: SubjectId, user: CurrentUser, db: DB, days: int = 365,
                   start: date | None = None, end: date | None = None) -> dict[str, Any]:
    ex = await get_readable(db, Exercise, "exercise", eid, user) if subject == user.id else await db.get(Exercise, eid)
    if not ex:
        raise HTTPException(404, "Nicht gefunden")
    s, e = st.period(start, end, days)
    return {"exercise": {"id": ex.id, "name": ex.name}, **await st.exercise_progress(db, subject, eid, s, e)}


@router.get("/stats/calendar")
async def calendar(subject: SubjectId, db: DB, days: int = 365, start: date | None = None, end: date | None = None) -> list[dict[str, Any]]:
    s, e = st.period(start, end, days)
    return await st.training_calendar(db, subject, s, e)


@router.get("/stats/weekly-volume")
async def weekly_volume(subject: SubjectId, db: DB, weeks: int = 12, end: date | None = None) -> dict[str, Any]:
    return await st.weekly_volume(db, subject, min(max(weeks, 1), 104), end)


@router.get("/stats/nutrition")
async def nutrition(subject: SubjectId, db: DB, days: int = 30, start: date | None = None, end: date | None = None) -> dict[str, Any]:
    s, e = st.period(start, end, days)
    return await st.nutrition_stats(db, subject, s, e)


@router.get("/stats/weight")
async def weight(subject: SubjectId, db: DB, days: int = 90, start: date | None = None, end: date | None = None) -> list[dict[str, Any]]:
    s, e = st.period(start, end, days)
    return await st.weight_series(db, subject, s, e)


@router.get("/stats/correlations")
async def correlations(subject: SubjectId, db: DB, days: int = 90, start: date | None = None, end: date | None = None) -> dict[str, Any]:
    s, e = st.period(start, end, days)
    return await st.correlations(db, subject, s, e)


@router.get("/stats/streaks")
async def streaks(subject: SubjectId, db: DB) -> dict[str, int]:
    return await st.streaks(db, subject)


@router.get("/stats/today")
async def today(user: CurrentUser, db: DB) -> dict[str, Any]:
    """Alles für das „Heute"-Dashboard in einem Request."""
    from app.api.training import training_today

    settings = await get_user_settings(db, user.id)
    t = date.today()
    hint = (await db.exec(select(CoachHint).where(CoachHint.user_id == user.id, ~CoachHint.dismissed)  # type: ignore[operator]
                          .order_by(CoachHint.created_at.desc()).limit(1))).first()
    return {
        "nutrition": await day_summary(db, user.id, t, settings["meal_slots"]),
        "training": await training_today(user, db),
        "weight": await st.weight_series(db, user.id, t - timedelta(days=30), t),
        "streaks": await st.streaks(db, user.id),
        "hint": hint.model_dump() if hint else None,
        "water_goal_ml": settings["water_goal_ml"],
    }


# ================================================================ Berichte
@router.get("/reports/week")
async def week_report(subject: SubjectId, db: DB, start: date | None = None) -> dict[str, Any]:
    s = st.week_start(start or (date.today() - timedelta(days=7)))
    e = s + timedelta(days=6)
    data = await st.period_summary(db, subject, s, e)
    prev = await st.period_summary(db, subject, s - timedelta(days=7), s - timedelta(days=1))
    ai = (await db.exec(select(CoachSummary).where(CoachSummary.user_id == subject, CoachSummary.period == "week",
                                                   CoachSummary.period_start == s))).first()
    return {"period": "week", "start": s, "end": e, "data": data, "previous": prev,
            "calendar": await st.training_calendar(db, subject, s, e),
            "nutrition_days": (await st.nutrition_stats(db, subject, s, e))["days"],
            "weight": await st.weight_series(db, subject, s, e),
            "coach": ai.model_dump() if ai else None}


@router.get("/reports/month")
async def month_report(subject: SubjectId, db: DB, month: str | None = None) -> dict[str, Any]:
    if month:
        y, m = (int(x) for x in month.split("-"))
        s = date(y, m, 1)
    else:
        t = date.today().replace(day=1) - timedelta(days=1)
        s = t.replace(day=1)
    e = (s.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    ai = (await db.exec(select(CoachSummary).where(CoachSummary.user_id == subject, CoachSummary.period == "month",
                                                   CoachSummary.period_start == s))).first()
    return {"period": "month", "start": s, "end": e, "data": await st.period_summary(db, subject, s, e),
            "calendar": await st.training_calendar(db, subject, s, e),
            "weekly_volume": await st.weekly_volume(db, subject, 5, e),
            "nutrition": await st.nutrition_stats(db, subject, s, e),
            "weight": await st.weight_series(db, subject, s, e),
            "coach": ai.model_dump() if ai else None}


@router.get("/reports")
async def list_reports(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(CoachSummary).where(CoachSummary.user_id == user.id, CoachSummary.period != "day")
                          .order_by(CoachSummary.period_start.desc()).limit(60))).all()
    return [{"id": r.id, "period": r.period, "period_start": r.period_start, "score": (r.data or {}).get("score")} for r in rows]


# ================================================================ Dashboards
WIDGET_TYPES = {"macros", "water", "workout_today", "weight_trend", "streak", "coach_hint", "muscle_heatmap",
                "calendar", "weekly_volume", "exercise_1rm", "metric", "kcal_trend", "quick_add", "body_stats"}


class DashboardIn(BaseModel):
    name: str
    position: int = 0
    widgets: list[dict[str, Any]] = []


def _clean(widgets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for w in widgets[:40]:
        if w.get("type") not in WIDGET_TYPES:
            raise HTTPException(422, f"Unbekannter Widget-Typ: {w.get('type')}")
        out.append({"id": str(w.get("id") or w["type"]), "type": w["type"], "w": min(max(int(w.get("w", 2)), 1), 4),
                    "h": min(max(int(w.get("h", 1)), 1), 4), "visible": bool(w.get("visible", True)),
                    "config": w.get("config") or {}})
    return out


@router.get("/dashboards")
async def list_dashboards(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(Dashboard).where(Dashboard.user_id == user.id).order_by(Dashboard.position))).all()
    return [r.model_dump() for r in rows]


@router.post("/dashboards")
async def create_dashboard(body: DashboardIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    d = Dashboard(user_id=user.id, name=body.name[:60], position=body.position, widgets=_clean(body.widgets))
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d.model_dump()


@router.put("/dashboards/{did}")
async def update_dashboard(did: int, body: DashboardIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    d = await get_owned(db, Dashboard, did, user.id)
    d.name, d.position, d.widgets = body.name[:60], body.position, _clean(body.widgets)
    db.add(d)
    await db.commit()
    return d.model_dump()


@router.delete("/dashboards/{did}")
async def delete_dashboard(did: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    d = await get_owned(db, Dashboard, did, user.id)
    await db.delete(d)
    await db.commit()
    return {"ok": True}
