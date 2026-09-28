"""Vollständiger Datenexport (JSON/CSV), Import und Kontolöschung."""

import csv
import io
import shutil
import zipfile
from datetime import date, datetime
from typing import Any

from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models import (
    AIUsage,
    BodyMeasurement,
    CardioSession,
    ChatConversation,
    ChatMessage,
    CoachHint,
    CoachNote,
    CoachProfile,
    CoachSummary,
    Dashboard,
    DayTemplate,
    Exercise,
    Favorite,
    Food,
    MealEntry,
    MealPlan,
    MetricDefinition,
    MetricEntry,
    Plan,
    PlanDay,
    PlanExercise,
    ProgressPhoto,
    Recipe,
    RecipeIngredient,
    User,
    UserProfile,
    UserSettings,
    WaterEntry,
    Workout,
    WorkoutSet,
)

USER_TABLES: list[type[SQLModel]] = [
    BodyMeasurement, CardioSession, CoachHint, CoachNote, CoachSummary, ChatConversation, ChatMessage,
    Dashboard, DayTemplate, Favorite, MealEntry, MealPlan, MetricDefinition, MetricEntry, ProgressPhoto,
    WaterEntry, Workout, WorkoutSet, AIUsage,
]
OWNER_TABLES: list[type[SQLModel]] = [Exercise, Food, Recipe, Plan]
EXPORT_VERSION = 1


def _ser(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    return v


def _row(obj: SQLModel) -> dict[str, Any]:
    return {k: _ser(v) for k, v in obj.model_dump().items()}


async def export_user(db: AsyncSession, user: User) -> dict[str, Any]:
    uid = user.id
    data: dict[str, Any] = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "user": {"email": user.email, "display_name": user.display_name, "role": user.role},
        "settings": (s.data if (s := await db.get(UserSettings, uid)) else {}),
        "profile": _row(p) if (p := await db.get(UserProfile, uid)) else None,
        "coach_profile": _row(c) if (c := await db.get(CoachProfile, uid)) else None,
        "tables": {},
    }
    for model in USER_TABLES:
        rows = (await db.exec(select(model).where(model.user_id == uid))).all()  # type: ignore[attr-defined]
        data["tables"][model.__tablename__] = [_row(r) for r in rows]
    for model in OWNER_TABLES:
        rows = (await db.exec(select(model).where(model.owner_id == uid))).all()  # type: ignore[attr-defined]
        data["tables"][model.__tablename__] = [_row(r) for r in rows]
    plan_ids = [p["id"] for p in data["tables"]["plan"]]
    days = (await db.exec(select(PlanDay).where(PlanDay.plan_id.in_(plan_ids)))).all() if plan_ids else []
    data["tables"]["plan_day"] = [_row(d) for d in days]
    day_ids = [d.id for d in days]
    pes = (await db.exec(select(PlanExercise).where(PlanExercise.plan_day_id.in_(day_ids)))).all() if day_ids else []
    data["tables"]["plan_exercise"] = [_row(p) for p in pes]
    recipe_ids = [r["id"] for r in data["tables"]["recipe"]]
    ings = (await db.exec(select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(recipe_ids)))).all() if recipe_ids else []
    data["tables"]["recipe_ingredient"] = [_row(i) for i in ings]
    # Slugs globaler Übungen für Import in andere Instanzen
    ex_ids = {s["exercise_id"] for s in data["tables"]["workout_set"]} | {p["exercise_id"] for p in data["tables"]["plan_exercise"]}
    glob = (await db.exec(select(Exercise).where(Exercise.id.in_(ex_ids), Exercise.owner_id.is_(None)))).all() if ex_ids else []
    data["global_exercise_slugs"] = {str(e.id): e.slug for e in glob}
    return data


def export_csv_zip(data: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, rows in data["tables"].items():
            if not rows:
                continue
            s = io.StringIO()
            cols = list(rows[0].keys())
            w = csv.DictWriter(s, fieldnames=cols, delimiter=";")
            w.writeheader()
            for r in rows:
                w.writerow({k: (str(v) if isinstance(v, dict | list) else v) for k, v in r.items()})
            z.writestr(f"{name}.csv", s.getvalue())
    return buf.getvalue()


def _parse(model: type[SQLModel], row: dict[str, Any], drop: set[str]) -> dict[str, Any]:
    fields = model.model_fields
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k in drop or k not in fields:
            continue
        ann = str(fields[k].annotation)
        if isinstance(v, str) and "datetime" in ann:
            v = datetime.fromisoformat(v)
        elif isinstance(v, str) and "date" in ann:
            v = date.fromisoformat(v)
        out[k] = v
    return out


async def import_user(db: AsyncSession, user: User, data: dict[str, Any]) -> dict[str, int]:
    """Importiert einen FitForge-Export additiv in das Konto (IDs werden neu vergeben)."""
    if data.get("version") != EXPORT_VERSION:
        raise ValueError("Unbekanntes Exportformat")
    t = data.get("tables", {})
    uid = user.id
    counts: dict[str, int] = {}
    idmap: dict[str, dict[int, int]] = {}

    def remember(table: str, old: int, new: int) -> None:
        idmap.setdefault(table, {})[old] = new

    async def add(model, row, table, drop=frozenset(), **over):
        obj = model(**{**_parse(model, row, {"id", *drop}), **over})
        db.add(obj)
        await db.flush()
        remember(table, row["id"], obj.id)
        counts[table] = counts.get(table, 0) + 1
        return obj

    slugs = data.get("global_exercise_slugs", {})
    global_by_slug = {e.slug: e.id for e in (await db.exec(select(Exercise).where(Exercise.owner_id.is_(None)))).all()}
    for old, slug in slugs.items():
        if slug in global_by_slug:
            remember("exercise", int(old), global_by_slug[slug])
    for r in t.get("exercise", []):
        await add(Exercise, r, "exercise", owner_id=uid, visibility="private")
    for r in t.get("food", []):
        await add(Food, r, "food", owner_id=uid, visibility="private")
    for r in t.get("recipe", []):
        await add(Recipe, r, "recipe", owner_id=uid, visibility="private")
    for r in t.get("recipe_ingredient", []):
        if (rid := idmap.get("recipe", {}).get(r["recipe_id"])) and (fid := idmap.get("food", {}).get(r["food_id"])):
            await add(RecipeIngredient, r, "recipe_ingredient", recipe_id=rid, food_id=fid)
    for r in t.get("plan", []):
        await add(Plan, r, "plan", owner_id=uid, visibility="private", is_active=False)
    for r in t.get("plan_day", []):
        if pid := idmap.get("plan", {}).get(r["plan_id"]):
            await add(PlanDay, r, "plan_day", plan_id=pid)
    for r in t.get("plan_exercise", []):
        did = idmap.get("plan_day", {}).get(r["plan_day_id"])
        eid = idmap.get("exercise", {}).get(r["exercise_id"])
        if did and eid:
            await add(PlanExercise, r, "plan_exercise", plan_day_id=did, exercise_id=eid)
    for r in t.get("workout", []):
        await add(Workout, r, "workout", user_id=uid, plan_day_id=idmap.get("plan_day", {}).get(r.get("plan_day_id")))
    for r in t.get("workout_set", []):
        wid = idmap.get("workout", {}).get(r["workout_id"])
        eid = idmap.get("exercise", {}).get(r["exercise_id"])
        if wid and eid:
            await add(WorkoutSet, r, "workout_set", user_id=uid, workout_id=wid, exercise_id=eid)
    for model, table in ((CardioSession, "cardio_session"), (BodyMeasurement, "body_measurement"),
                         (WaterEntry, "water_entry"), (CoachNote, "coach_note"), (DayTemplate, "day_template")):
        for r in t.get(table, []):
            await add(model, r, table, user_id=uid)
    for r in t.get("meal_entry", []):
        await add(MealEntry, r, "meal_entry", user_id=uid, food_id=idmap.get("food", {}).get(r.get("food_id")),
                  recipe_id=idmap.get("recipe", {}).get(r.get("recipe_id")))
    for r in t.get("metric_definition", []):
        await add(MetricDefinition, r, "metric_definition", user_id=uid)
    for r in t.get("metric_entry", []):
        if mid := idmap.get("metric_definition", {}).get(r["metric_id"]):
            await add(MetricEntry, r, "metric_entry", user_id=uid, metric_id=mid)
    await db.commit()
    return counts


async def delete_user_data(db: AsyncSession, user: User) -> None:
    """Löscht Konto inkl. aller Daten. Von anderen genutzte geteilte Übungen/Lebensmittel
    werden in die globale Bibliothek übernommen, damit deren Verlauf erhalten bleibt."""
    uid = user.id
    for model, ref_model, ref_col, ref_user in (
        (Exercise, WorkoutSet, WorkoutSet.exercise_id, WorkoutSet.user_id),
        (Food, MealEntry, MealEntry.food_id, MealEntry.user_id),
    ):
        owned = (await db.exec(select(model).where(model.owner_id == uid, model.visibility != "private"))).all()
        for obj in owned:
            used = (await db.exec(select(ref_model.id).where(ref_col == obj.id, ref_user != uid).limit(1))).first()
            if used:
                obj.owner_id = None
                obj.visibility = "public"
                db.add(obj)
    await db.commit()
    shutil.rmtree(settings.uploads_dir / str(uid), ignore_errors=True)
    await db.delete(user)
    await db.commit()
