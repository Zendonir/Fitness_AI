"""Tools für den KI-Coach.

Sicherheitsprinzip: Kein Tool hat einen user_id-Parameter. Alle Abfragen laufen über `ctx.user.id`.
Schreibende Tools legen nur eine PendingAction an – ausgeführt wird erst nach Bestätigung.
"""

import difflib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.context import jsonable
from app.ai.providers.base import ToolCall, ToolSpec
from app.core.access import readable_clause
from app.models import (
    CoachNote,
    CoachProfile,
    Exercise,
    Food,
    MetricDefinition,
    MetricEntry,
    PendingAction,
    Plan,
    PlanDay,
    PlanExercise,
    Recipe,
    User,
    UserProfile,
    Workout,
    WorkoutSet,
)
from app.services import stats as st
from app.services.app_settings import get_user_settings
from app.services.meals import day_summary, recipe_nutrition
from app.services.nutrition import body_from_profile, compute_targets, validate_targets
from app.services.targets import latest_weight, user_targets

READ_ONLY = {"type": "object", "properties": {}, "additionalProperties": False}


def _days(default: int, maximum: int = 365) -> dict[str, Any]:
    return {"type": "integer", "minimum": 1, "maximum": maximum, "default": default, "description": "Zeitraum in Tagen"}


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec("get_today_status", "Heutiger Stand: Makros gegessen vs. Ziel, Wasser, geplantes Training.", READ_ONLY),
    ToolSpec("get_workouts", "Letzte Krafttrainings mit Übungen, Sätzen, Gewichten und RPE sowie Ausdauereinheiten.",
             {"type": "object", "properties": {"days": _days(14, 90)}}),
    ToolSpec("get_exercise_progress", "Verlauf einer Übung: geschätztes 1RM (Epley), Volumen, Rekorde pro Wiederholungszahl.",
             {"type": "object", "properties": {"exercise": {"type": "string"}, "days": _days(180)}, "required": ["exercise"]}),
    ToolSpec("get_personal_records", "Persönliche Rekorde (neue Bestleistungen) im Zeitraum.",
             {"type": "object", "properties": {"days": _days(90)}}),
    ToolSpec("get_training_volume", "Arbeitssätze pro Muskelgruppe im Zeitraum.", {"type": "object", "properties": {"days": _days(7, 60)}}),
    ToolSpec("get_active_plan", "Aktiver Trainingsplan mit Tagen, Wochentagen, Übungen, Sätzen, Wiederholungsbereichen, "
             "Pausen, Supersätzen und aktueller Woche.", READ_ONLY),
    ToolSpec("list_plans", "Eigene Trainingspläne (inkl. aktivem) und verfügbare Vorlagen auflisten.", READ_ONLY),
    ToolSpec("get_plan", "Einen bestimmten eigenen Plan oder eine Vorlage mit allen Details laden.",
             {"type": "object", "properties": {"plan": {"type": "string", "description": "Planname"}}, "required": ["plan"]}),
    ToolSpec("get_nutrition", "Ernährung: Tageswerte und Durchschnitt vs. Ziele, Top-Lebensmittel.",
             {"type": "object", "properties": {"days": _days(7, 90)}}),
    ToolSpec("get_nutrition_targets", "Aktuelle Tagesziele (Trainings-/Ruhetag), Bedarf (TDEE) und feste Untergrenzen.", READ_ONLY),
    ToolSpec("get_weight_trend", "Gewichtsverlauf mit 7-Tage-Mittel.", {"type": "object", "properties": {"days": _days(30)}}),
    ToolSpec("get_metrics", "Eigene Metriken des Benutzers (z. B. Schlaf, Stimmung, Schritte) mit Werten.",
             {"type": "object", "properties": {"days": _days(14, 90)}}),
    ToolSpec("search_exercises", "Übungen in der Bibliothek suchen (Name, Muskelgruppe).",
             {"type": "object", "properties": {"query": {"type": "string"}, "muscle": {"type": "string"}}}),
    ToolSpec("search_foods", "Lebensmittel/Rezepte des Benutzers und der Datenbank suchen (Nährwerte pro 100 g).",
             {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
    ToolSpec("save_memory", "Wichtige, dauerhafte Erkenntnis über den Benutzer im Gedächtnis speichern (Ziel, Vorliebe, "
             "Einschränkung, wichtiges Ereignis). Nicht für Kleinigkeiten.",
             {"type": "object", "properties": {
                 "content": {"type": "string", "maxLength": 500},
                 "category": {"type": "string", "enum": ["general", "training", "nutrition", "health", "preference", "goal"]},
                 "importance": {"type": "integer", "minimum": 1, "maximum": 3}}, "required": ["content"]}),
    # --- schreibend (Bestätigung erforderlich)
    ToolSpec("propose_log_meal", "Mahlzeit(en) zum Loggen vorschlagen. Der Benutzer muss bestätigen.",
             {"type": "object", "properties": {
                 "day": {"type": "string", "description": "YYYY-MM-DD, Standard heute"},
                 "slot": {"type": "string", "description": "Mahlzeiten-Slot, z. B. Abendessen"},
                 "items": {"type": "array", "items": {"type": "object", "properties": {
                     "name": {"type": "string"}, "food_id": {"type": "integer"}, "recipe_id": {"type": "integer"},
                     "grams": {"type": "number"}, "servings": {"type": "number"}, "kcal": {"type": "number"},
                     "protein": {"type": "number"}, "carbs": {"type": "number"}, "fat": {"type": "number"},
                     "fiber": {"type": "number"}}, "required": ["name"]}}}, "required": ["items"]}),
    ToolSpec("propose_nutrition_goal", "Ernährungsziel ändern (Aufbau/Erhalt/Defizit und/oder eigene Makroziele). "
             "Untergrenzen werden automatisch erzwungen. Bestätigung erforderlich.",
             {"type": "object", "properties": {
                 "goal": {"type": "string", "enum": ["bulk", "maintain", "cut"]},
                 "training": {"type": "object", "properties": {k: {"type": "number"} for k in ("kcal", "protein", "carbs", "fat")}},
                 "rest": {"type": "object", "properties": {k: {"type": "number"} for k in ("kcal", "protein", "carbs", "fat")}},
                 "reason": {"type": "string"}}}),
    ToolSpec("propose_plan_changes",
             "Trainingsplan des Benutzers ändern (Standard: aktiver Plan). Nutze das, wenn der Benutzer eine Änderung "
             "wünscht ODER du aufgrund von Fortschritt, RPE, Regeneration oder Zeitbudget eine Anpassung empfiehlst. "
             "Rufe vorher get_active_plan bzw. get_plan auf, um exakte Tag- und Übungsnamen zu kennen. "
             "Der Benutzer sieht ein Vorher/Nachher und bestätigt. Operationen: "
             "add/remove/update/replace/move (Übungen), add_day/remove_day/rename_day/set_weekday/move_day (Tage), "
             "set_plan (name, weeks, deload_weeks, deload_factor). position ist 1-basiert.",
             {"type": "object", "properties": {
                 "plan": {"type": "string", "description": "Planname; leer = aktiver Plan"},
                 "reason": {"type": "string", "description": "Kurze Begründung für den Benutzer"},
                 "allow_duplicates": {"type": "boolean", "description": "Gleiche Übung mehrfach an einem Tag erlauben"},
                 "changes": {"type": "array", "items": {"type": "object", "properties": {
                     "op": {"type": "string", "enum": ["add", "remove", "update", "replace", "move", "add_day", "remove_day",
                                                       "rename_day", "set_weekday", "move_day", "set_plan"]},
                     "day": {"type": "string", "description": "Name des Plantags"},
                     "new_name": {"type": "string", "description": "Neuer Tagname (rename_day/add_day)"},
                     "weekday": {"type": "string", "description": "Mo, Di, Mi, Do, Fr, Sa, So oder leer"},
                     "exercise": {"type": "string", "description": "Bestehende Übung (remove/update/replace/move)"},
                     "new_exercise": {"type": "string", "description": "Neue Übung aus der Bibliothek (add/replace)"},
                     "position": {"type": "integer"},
                     "sets": {"type": "integer"}, "rep_min": {"type": "integer"}, "rep_max": {"type": "integer"},
                     "rest_seconds": {"type": "integer"}, "target_rpe": {"type": "number"},
                     "superset_group": {"type": "string"}, "notes": {"type": "string"},
                     "name": {"type": "string"}, "weeks": {"type": "integer"},
                     "deload_weeks": {"type": "array", "items": {"type": "integer"}}, "deload_factor": {"type": "number"}},
                     "required": ["op"]}}}, "required": ["changes"]}),
    ToolSpec("propose_new_plan",
             "Einen komplett neuen Trainingsplan für den Benutzer erstellen (z. B. bei neuem Ziel, anderer Frequenz oder "
             "wenn der bisherige Plan ersetzt werden soll). Nur Übungen aus der Bibliothek verwenden. Bestätigung erforderlich.",
             {"type": "object", "properties": {
                 "name": {"type": "string"}, "description": {"type": "string"},
                 "weeks": {"type": "integer"}, "deload_weeks": {"type": "array", "items": {"type": "integer"}},
                 "activate": {"type": "boolean", "description": "Nach Bestätigung als aktiven Plan setzen"},
                 "reason": {"type": "string"},
                 "days": {"type": "array", "items": {"type": "object", "properties": {
                     "name": {"type": "string"}, "weekday": {"type": "string"},
                     "exercises": {"type": "array", "items": {"type": "object", "properties": {
                     "exercise": {"type": "string"}, "sets": {"type": "integer"}, "rep_min": {"type": "integer"},
                     "rep_max": {"type": "integer"}, "rest_seconds": {"type": "integer"}, "target_rpe": {"type": "number"},
                     "superset_group": {"type": "string", "description": "z. B. a – gleiche Buchstaben = Supersatz"},
                     "notes": {"type": "string"}}, "required": ["exercise"]}}},
                     "required": ["name", "exercises"]}}}, "required": ["name", "days"]}),
    ToolSpec("propose_workout", "Ein konkretes Workout für heute vorschlagen (z. B. Kurzversion für wenig Zeit). "
             "Nach Bestätigung wird es im Live-Modus vorbereitet.",
             {"type": "object", "properties": {
                 "name": {"type": "string"},
                 "exercises": {"type": "array", "items": {"type": "object", "properties": {
                     "exercise": {"type": "string"}, "sets": {"type": "integer"}, "reps": {"type": "integer"},
                     "weight_kg": {"type": "number"}}, "required": ["exercise", "sets", "reps"]}}},
             "required": ["name", "exercises"]}),
    ToolSpec("propose_log_weight", "Körpergewicht loggen. Bestätigung erforderlich.",
             {"type": "object", "properties": {"weight_kg": {"type": "number"}, "day": {"type": "string"}}, "required": ["weight_kg"]}),
    ToolSpec("propose_profile_update", "Coach-Profil aktualisieren (Ziele, Vorlieben, Einschränkungen, Equipment, Zeiten). "
             "Bestätigung erforderlich.",
             {"type": "object", "properties": {
                 "field": {"type": "string", "enum": ["goals", "experience", "preferences", "dislikes", "limitations", "equipment", "schedule"]},
                 "value": {"type": "string"}}, "required": ["field", "value"]}),
]
WRITE_TOOLS = {t.name for t in TOOL_SPECS if t.name.startswith("propose_")}
CONSENT_FOR = {"get_nutrition": "nutrition", "get_nutrition_targets": "nutrition", "get_today_status": "nutrition",
               "get_weight_trend": "body", "get_metrics": "metrics", "propose_log_weight": "body",
               "get_workouts": "training", "get_exercise_progress": "training", "get_personal_records": "training",
               "get_training_volume": "training", "get_active_plan": "training", "list_plans": "training", "get_plan": "training"}


@dataclass
class ToolContext:
    db: AsyncSession
    user: User
    conversation_id: int | None = None
    consents: dict[str, bool] = field(default_factory=dict)
    pending: list[PendingAction] = field(default_factory=list)
    allowed: set[str] | None = None


async def make_context(db: AsyncSession, user: User, conversation_id: int | None = None) -> ToolContext:
    s = await get_user_settings(db, user.id)
    return ToolContext(db=db, user=user, conversation_id=conversation_id, consents=s["ai"].get("consents", {}))


async def find_exercise(ctx: ToolContext, name: str) -> Exercise | None:
    rows = (await ctx.db.exec(select(Exercise).where(readable_clause(Exercise, "exercise", ctx.user.id)))).all()
    low = name.lower().strip()
    for e in rows:
        if e.name.lower() == low or (e.slug or "") == low:
            return e
    contains = [e for e in rows if low in e.name.lower()]
    if contains:
        return min(contains, key=lambda e: len(e.name))
    close = difflib.get_close_matches(low, [e.name.lower() for e in rows], n=1, cutoff=0.6)
    return next((e for e in rows if close and e.name.lower() == close[0]), None)


def _dump(v: Any) -> str:
    return json.dumps(jsonable(v), ensure_ascii=False, default=str)[:12000]


async def _active_plan(ctx: ToolContext) -> Plan | None:
    return (await ctx.db.exec(select(Plan).where(Plan.owner_id == ctx.user.id, Plan.is_active))).first()


async def _find_plan(ctx: ToolContext, name: str | None, include_templates: bool = False) -> Plan | None:
    rows = (await ctx.db.exec(select(Plan).where(readable_clause(Plan, "plan", ctx.user.id)))).all()
    if not include_templates:
        rows = [p for p in rows if p.owner_id == ctx.user.id]
    key = str(name or "").strip().lower()
    exact = [p for p in rows if p.name.lower() == key]
    own_first = sorted(exact or [p for p in rows if key and key in p.name.lower()], key=lambda p: (p.owner_id != ctx.user.id, not p.is_active))
    return own_first[0] if own_first else None


async def _pending(ctx: ToolContext, tool: str, args: dict[str, Any], summary: str, diff: dict[str, Any]) -> str:
    pa = PendingAction(user_id=ctx.user.id, conversation_id=ctx.conversation_id, tool=tool, args=jsonable(args),
                       summary=summary, diff=jsonable(diff))
    ctx.db.add(pa)
    await ctx.db.commit()
    await ctx.db.refresh(pa)
    ctx.pending.append(pa)
    return _dump({"status": "pending_confirmation", "action_id": pa.id, "summary": summary,
                  "hinweis": "Der Benutzer sieht jetzt einen Bestätigungsdialog. Noch nichts wurde geändert."})


async def execute_tool(ctx: ToolContext, call: ToolCall) -> str:
    name, a = call.name, call.arguments or {}
    if ctx.allowed is not None and name not in ctx.allowed:
        return _dump({"error": f"Tool {name} ist in diesem Kontext nicht erlaubt"})
    consent = CONSENT_FOR.get(name)
    if consent and not ctx.consents.get(consent, False):
        return _dump({"error": f"Der Benutzer hat die Datenkategorie '{consent}' nicht für die KI freigegeben."})
    db, uid = ctx.db, ctx.user.id
    today = date.today()

    if name == "get_today_status":
        s = await get_user_settings(db, uid)
        from app.api.training import next_plan_day

        return _dump({"nutrition": await day_summary(db, uid, today, s["meal_slots"]), "plan": await next_plan_day(db, uid)})

    if name == "get_workouts":
        days = int(a.get("days", 14))
        a_, b_ = st.day_bounds(today - timedelta(days=days - 1), today)
        ws = (await db.exec(select(Workout).where(Workout.user_id == uid, Workout.started_at >= a_, Workout.started_at < b_)
                            .order_by(Workout.started_at.desc()).limit(40))).all()
        out = []
        for w in ws:
            sets = (await db.exec(select(WorkoutSet).where(WorkoutSet.workout_id == w.id, WorkoutSet.user_id == uid)
                                  .order_by(WorkoutSet.position))).all()
            by_ex: dict[str, list[str]] = {}
            for s_ in sets:
                e = await db.get(Exercise, s_.exercise_id)
                by_ex.setdefault(e.name if e else "?", []).append(
                    f"{s_.reps}x{s_.weight_kg:g}kg" + (f"@{s_.rpe:g}" if s_.rpe else "") + (" (W)" if s_.is_warmup else ""))
            out.append({"day": st.local_date(w.started_at), "name": w.name, "rating": w.rating, "deload": w.is_deload,
                        "notes": w.notes, "exercises": by_ex})
        cal = await st.training_calendar(db, uid, today - timedelta(days=days - 1), today)
        return _dump({"workouts": out, "cardio_days": [c for c in cal if c["cardio"]]})

    if name == "get_exercise_progress":
        ex = await find_exercise(ctx, str(a.get("exercise", "")))
        if not ex:
            return _dump({"error": "Übung nicht gefunden"})
        days = int(a.get("days", 180))
        return _dump({"exercise": ex.name, **await st.exercise_progress(db, uid, ex.id, today - timedelta(days=days), today)})

    if name == "get_personal_records":
        s = await st.period_summary(db, uid, today - timedelta(days=int(a.get("days", 90))), today)
        return _dump({"prs": s["training"]["prs"]})

    if name == "get_training_volume":
        return _dump(await st.muscle_volume(db, uid, today - timedelta(days=int(a.get("days", 7)) - 1), today))

    if name == "get_active_plan":
        from app.ai import plan_edit
        from app.api.training import plan_week

        plan = await _active_plan(ctx)
        if not plan:
            return _dump({"active_plan": None})
        week, deload = plan_week(plan)
        return _dump({**await plan_edit.snapshot(db, plan), "current_week": week, "deload_week": deload})

    if name == "list_plans":
        rows = (await db.exec(select(Plan).where(readable_clause(Plan, "plan", uid)))).all()
        return _dump([{"name": p.name, "own": p.owner_id == uid, "active": p.is_active and p.owner_id == uid,
                       "template": p.owner_id is None, "weeks": p.weeks} for p in rows])

    if name == "get_plan":
        from app.ai import plan_edit

        plan = await _find_plan(ctx, a.get("plan"), include_templates=True)
        return _dump(await plan_edit.snapshot(db, plan) if plan else {"error": "Plan nicht gefunden"})

    if name == "get_nutrition":
        days = int(a.get("days", 7))
        n = await st.nutrition_stats(db, uid, today - timedelta(days=days - 1), today)
        return _dump({k: n[k] for k in ("average", "logged_days", "adherence_pct", "protein_hit_pct", "distribution_pct",
                                        "top_protein")} | {"days": [
            {k: d.get(k) for k in ("day", "kcal", "protein", "carbs", "fat", "target_kcal", "target_protein", "logged")}
            for d in n["days"]]})

    if name == "get_nutrition_targets":
        return _dump(await user_targets(db, uid))

    if name == "get_weight_trend":
        return _dump({"trend": await st.weight_series(db, uid, today - timedelta(days=int(a.get("days", 30))), today)})

    if name == "get_metrics":
        defs = (await db.exec(select(MetricDefinition).where(MetricDefinition.user_id == uid, ~col(MetricDefinition.archived)))).all()
        since = today - timedelta(days=int(a.get("days", 14)))
        out = []
        for m in defs:
            es = (await db.exec(select(MetricEntry).where(MetricEntry.metric_id == m.id, MetricEntry.user_id == uid,
                                                          MetricEntry.day >= since).order_by(MetricEntry.day))).all()
            out.append({"name": m.name, "type": m.kind, "unit": m.unit, "target": m.target,
                        "values": [{"day": e.day, "value": e.value_num if e.value_text is None else e.value_text} for e in es]})
        return _dump({"metrics": out})

    if name == "search_exercises":
        rows = (await db.exec(select(Exercise).where(readable_clause(Exercise, "exercise", uid)))).all()
        q, m = (a.get("query") or "").lower(), a.get("muscle")
        res = [e for e in rows if (not q or q in e.name.lower()) and (not m or m in e.primary_muscles + e.secondary_muscles)]
        return _dump([{"name": e.name, "equipment": e.equipment, "primary": e.primary_muscles} for e in res[:25]])

    if name == "search_foods":
        q = str(a.get("query", ""))
        from app.services.food_search import search_local

        foods = await search_local(db, uid, q, limit=10)
        recipes = (await db.exec(select(Recipe).where(readable_clause(Recipe, "recipe", uid), col(Recipe.name).ilike(f"%{q}%")).limit(5))).all()
        return _dump({
            "foods_per_100g": [{"food_id": f.id, "name": f.name, "brand": f.brand, "source": f.source, "kcal": f.kcal,
                                "protein": f.protein, "carbs": f.carbs, "fat": f.fat, "serving_g": f.serving_g} for f in foods],
            "recipes_per_serving": [{"recipe_id": r.id, "name": r.name, **(await recipe_nutrition(db, r))["per_serving"]} for r in recipes],
        })

    if name == "save_memory":
        content = str(a.get("content", "")).strip()[:500]
        if not content:
            return _dump({"error": "leer"})
        existing = (await db.exec(select(CoachNote).where(CoachNote.user_id == uid))).all()
        if any(difflib.SequenceMatcher(None, n.content.lower(), content.lower()).ratio() > 0.85 for n in existing):
            return _dump({"status": "already_known"})
        db.add(CoachNote(user_id=uid, content=content, category=a.get("category", "general"),
                         importance=int(a.get("importance", 2)), source="coach"))
        await db.commit()
        return _dump({"status": "saved"})

    # ------------------------------------------------ schreibende Vorschläge
    if name == "propose_log_meal":
        items = a.get("items") or []
        if not items:
            return _dump({"error": "keine Einträge"})
        total = sum(float(i.get("kcal") or 0) for i in items)
        summary = f"{len(items)} Eintrag/Einträge in „{a.get('slot') or 'Snacks'}“ loggen (~{round(total)} kcal)"
        return await _pending(ctx, name, a, summary, {"items": items})

    if name == "propose_nutrition_goal":
        profile = await db.get(UserProfile, uid) or UserProfile(user_id=uid)
        body = body_from_profile(profile, await latest_weight(db, uid))
        before = compute_targets(body, profile.custom_targets)
        if a.get("goal"):
            body.goal = a["goal"]
        custom = {k: validate_targets(a[k], body) for k in ("training", "rest") if a.get(k)}
        after = compute_targets(body, custom or profile.custom_targets)
        clamped = any(a.get(k, {}).get(m) is not None and after[k][m] > float(a[k][m]) for k in ("training", "rest") for m in ("kcal", "protein"))
        diff = {"before": {k: before[k] for k in ("goal", "training", "rest")}, "after": {k: after[k] for k in ("goal", "training", "rest")},
                "floors": after["floors"], "clamped": clamped}
        summary = "Ernährungsziel anpassen" + (" (auf Untergrenzen angehoben)" if clamped else "")
        return await _pending(ctx, name, {"goal": body.goal, "custom": custom, "reason": a.get("reason", "")}, summary, diff)

    if name == "propose_plan_changes":
        from app.ai import plan_edit

        plan = await _find_plan(ctx, a.get("plan")) if a.get("plan") else await _active_plan(ctx)
        if not plan:
            return _dump({"error": "Plan nicht gefunden" if a.get("plan") else "Kein aktiver Plan – nutze list_plans oder propose_new_plan"})
        if plan.owner_id != uid:
            return _dump({"error": "Vorlagen können nicht direkt geändert werden – erstelle mit propose_new_plan eine eigene Version"})
        before = await plan_edit.snapshot(db, plan)
        after, warnings = await plan_edit.apply_changes(before, a.get("changes") or [], lambda n: find_exercise(ctx, n))
        if after == before:
            return _dump({"error": "Keine wirksame Änderung", "hinweise": warnings, "plan": before})
        dupes = [w for w in warnings if "mehrfach" in w]
        if dupes and not a.get("allow_duplicates"):
            return _dump({"error": "Übung doppelt am selben Tag – bitte eine andere Übung wählen oder die bestehende anpassen "
                                   "(allow_duplicates=true, falls wirklich gewollt)", "hinweise": dupes})
        summary = f"Plan „{plan.name}“ anpassen" + (f": {a.get('reason')}" if a.get("reason") else "")
        return await _pending(ctx, name, {"plan_id": plan.id, "after": after, "base": plan_edit.stamp(plan),
                                          "reason": a.get("reason", "")},
                              summary, {"before": before, "after": after, "warnings": warnings, "reason": a.get("reason", "")})

    if name == "propose_new_plan":
        from app.ai import plan_edit

        warnings: list[str] = []
        days = []
        for d in (a.get("days") or [])[:7]:
            items = []
            for e in d.get("exercises") or []:
                ex = await find_exercise(ctx, str(e.get("exercise", "")))
                if not ex:
                    warnings.append(f"Übung „{e.get('exercise')}“ nicht gefunden – ausgelassen")
                    continue
                prog = ex.progression or {}
                items.append({"exercise_id": ex.id, "exercise": ex.name, "sets": 3, "rep_min": prog.get("rep_min", 8),
                              "rep_max": prog.get("rep_max", 12), "target_rpe": 8.0, "rest_seconds": 120,
                              "superset_group": None, "notes": "", **plan_edit._clean_fields(e)})
            days.append({"id": None, "day": str(d.get("name") or f"Tag {len(days) + 1}")[:80],
                         "weekday": plan_edit.parse_weekday(d.get("weekday")), "notes": "", "exercises": items})
        if not days or not any(d["exercises"] for d in days):
            return _dump({"error": "Plan ohne gültige Übungen", "hinweise": warnings})
        weeks = min(max(int(a.get("weeks") or 4), 1), 52)
        spec = {"name": str(a["name"])[:120], "description": str(a.get("description") or "")[:1000], "weeks": weeks,
                "deload_weeks": sorted({int(w) for w in a.get("deload_weeks") or [] if 1 <= int(w) <= weeks}),
                "deload_factor": 0.6, "activate": bool(a.get("activate", True)), "days": days}
        return await _pending(ctx, name, {"spec": spec, "reason": a.get("reason", "")},
                              f"Neuer Plan „{spec['name']}“" + (" (wird aktiviert)" if spec["activate"] else ""),
                              {"before": [], "after": spec, "warnings": warnings, "reason": a.get("reason", "")})

    if name == "propose_workout":
        resolved = []
        for it in a.get("exercises", []):
            ex = await find_exercise(ctx, str(it.get("exercise", "")))
            if ex:
                resolved.append({"exercise_id": ex.id, "exercise": ex.name, "sets": int(it.get("sets") or 3),
                                 "reps": int(it.get("reps") or 10), "weight_kg": float(it.get("weight_kg") or 0)})
        if not resolved:
            return _dump({"error": "Keine der Übungen gefunden"})
        return await _pending(ctx, name, {"name": a.get("name") or "Coach-Workout", "exercises": resolved},
                              f"Workout „{a.get('name') or 'Coach-Workout'}“ mit {len(resolved)} Übungen vorbereiten",
                              {"exercises": resolved})

    if name == "propose_log_weight":
        w = float(a.get("weight_kg") or 0)
        if not 20 < w < 400:
            return _dump({"error": "unplausibles Gewicht"})
        return await _pending(ctx, name, {"weight_kg": w, "day": a.get("day") or today.isoformat()},
                              f"Gewicht {w:g} kg eintragen", {"weight_kg": w})

    if name == "propose_profile_update":
        cp = await db.get(CoachProfile, uid) or CoachProfile(user_id=uid)
        f = a.get("field")
        if f not in {"goals", "experience", "preferences", "dislikes", "limitations", "equipment", "schedule"}:
            return _dump({"error": "unbekanntes Feld"})
        return await _pending(ctx, name, {"field": f, "value": str(a.get("value", ""))[:2000]},
                              f"Coach-Profil: {f} aktualisieren", {"before": getattr(cp, f), "after": a.get("value")})

    return _dump({"error": f"Unbekanntes Tool {name}"})
