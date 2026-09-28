"""Hintergrundlogik des Coaches: Zusammenfassungen, Berichte, proaktive Hinweise, Briefings.

Alle Funktionen arbeiten auch ohne KI: dann werden die Texte regelbasiert erzeugt.
"""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.client import ai_available, parse_json, run_llm
from app.ai.context import build_system_prompt, jsonable
from app.ai.providers.base import Message
from app.ai.usage import AIDisabledError, AILimitError
from app.models import CoachHint, CoachSummary, Plan, User, Workout
from app.services import stats as st
from app.services.app_settings import get_user_settings
from app.services.push import notify_user
from app.services.targets import user_targets

log = logging.getLogger(__name__)


def _fmt_summary(s: dict[str, Any]) -> str:
    t, n, b = s["training"], s["nutrition"], s["body"]
    parts = [f"{t['workouts']} Krafteinheit(en), {t['sets']} Arbeitssätze, {t['tonnage_kg']} kg Volumen"]
    if s["cardio"]["sessions"]:
        parts.append(f"{s['cardio']['sessions']}× Ausdauer ({s['cardio']['minutes']} min, {s['cardio']['distance_km']} km)")
    if n["logged_days"]:
        parts.append(f"Ø {n['average']['kcal']:.0f} kcal / {n['average']['protein']:.0f} g Protein "
                     f"(Ziel {n['target_kcal_avg']} / {n['target_protein_avg']} g, {n['logged_days']} Tage geloggt)")
    if b["weight_change"] is not None:
        parts.append(f"Gewichtstrend {b['weight_change']:+.1f} kg (Ø {b['weight_end']:.1f} kg)")
    if t["prs"]:
        parts.append("PRs: " + ", ".join(sorted({p["exercise"] for p in t["prs"]})))
    return "; ".join(parts) + "."


async def _llm_text(db: AsyncSession, user: User, task: str, instruction: str, data: dict[str, Any], json_mode: bool = False,
                    max_tokens: int = 2000) -> str | None:
    ok, _ = await ai_available(db, user)
    if not ok:
        return None
    try:
        system = await build_system_prompt(db, user)
        res = await run_llm(db, user, task, system, [Message("user", instruction + "\n\nDaten (JSON):\n" +
                                                             json.dumps(jsonable(data), ensure_ascii=False, default=str))],
                            max_tokens=max_tokens, json_mode=json_mode)
        return res.text
    except (AIDisabledError, AILimitError) as e:
        log.info("KI übersprungen für %s: %s", user.id, e)
    except Exception:  # noqa: BLE001 - Hintergrundjob darf nicht abbrechen
        log.exception("KI-Aufruf %s fehlgeschlagen", task)
    return None


async def _consented(db: AsyncSession, user_id: int, data: dict[str, Any]) -> dict[str, Any]:
    c = (await get_user_settings(db, user_id))["ai"].get("consents", {})
    out = dict(data)
    if not c.get("nutrition"):
        for k in ("nutrition", "targets_today", "totals", "targets", "water_ml"):
            out.pop(k, None)
    if not c.get("body"):
        out.pop("body", None)
    if not c.get("training"):
        out.pop("training", None)
        out.pop("cardio", None)
    return out


async def daily_summary(db: AsyncSession, user: User, day: date | None = None) -> CoachSummary:
    day = day or date.today() - timedelta(days=1)
    data = await st.period_summary(db, user.id, day, day)
    text = _fmt_summary(data)
    llm = await _llm_text(db, user, "summary", "Fasse den Tag in 2–3 Sätzen als Verlaufsnotiz für dein Gedächtnis zusammen "
                          "(sachlich, mit Zahlen, keine Anrede).", await _consented(db, user.id, data), max_tokens=400)
    return await _store(db, user.id, "day", day, llm or text, {"metrics": jsonable(data)})


async def _store(db: AsyncSession, user_id: int, period: str, start: date, content: str, data: dict[str, Any]) -> CoachSummary:
    row = (await db.exec(select(CoachSummary).where(CoachSummary.user_id == user_id, CoachSummary.period == period,
                                                    CoachSummary.period_start == start))).first()
    row = row or CoachSummary(user_id=user_id, period=period, period_start=start)
    row.content, row.data, row.created_at = content.strip(), data, datetime.now(UTC)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


REPORT_INSTRUCTION = """Erstelle den {label} als JSON mit genau diesen Feldern:
{{"score": Zahl 1-10 (Gesamtbewertung), "headline": kurzer Titel, "summary": 3-4 Sätze,
"highlights": [bis 4 Stichpunkte], "improvements": [bis 3 Stichpunkte],
"recommendations": [3-5 konkrete, umsetzbare Empfehlungen für den nächsten Zeitraum],
"training_score": 1-10, "nutrition_score": 1-10, "recovery_note": ein Satz}}
Nur JSON ausgeben. Beachte die Leitplanken (keine Diagnosen, keine Crash-Diäten)."""


def _rule_report(data: dict[str, Any], prev: dict[str, Any] | None) -> dict[str, Any]:
    t, n = data["training"], data["nutrition"]
    score_t = min(10, 3 + t["workouts"] * 2)
    score_n = round(min(10, max(1, (n["protein_hit_pct"] + n["adherence_pct"]) / 20))) if n["logged_days"] else 3
    recs = []
    if n["logged_days"] and n["protein_hit_pct"] < 60:
        recs.append("Protein an mehr Tagen erreichen – plane eine proteinreiche Mahlzeit pro Tag fest ein.")
    if t["workouts"] < 2:
        recs.append("Plane feste Trainingstermine im Kalender ein, mindestens 2–3 Einheiten.")
    if n["logged_days"] < 5:
        recs.append("Logge deine Ernährung an mindestens 5 Tagen, um genauere Empfehlungen zu erhalten.")
    if t["avg_rpe"] and t["avg_rpe"] >= 9:
        recs.append("Hohe Anstrengung (RPE ≥ 9): achte auf Schlaf und plane ggf. eine Deload-Woche.")
    if not recs:
        recs.append("Weiter so – halte die Progression bei und steigere wo möglich Gewicht oder Wiederholungen.")
    return {"score": round((score_t + score_n) / 2), "headline": "Dein Rückblick", "summary": _fmt_summary(data),
            "highlights": [f"PR: {p['exercise']}" for p in t["prs"][:4]], "improvements": [], "recommendations": recs,
            "training_score": score_t, "nutrition_score": score_n, "recovery_note": "", "generated_by": "rules"}


async def period_report(db: AsyncSession, user: User, period: str, start: date) -> CoachSummary:
    if period == "week":
        end, prev_start, label = start + timedelta(days=6), start - timedelta(days=7), "Wochenrückblick"
    else:
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        prev_start, label = (start - timedelta(days=1)).replace(day=1), "Monatsrückblick"
    data = await st.period_summary(db, user.id, start, end)
    prev = await st.period_summary(db, user.id, prev_start, start - timedelta(days=1))
    report = _rule_report(data, prev)
    text = await _llm_text(db, user, "weekly_report", REPORT_INSTRUCTION.format(label=label),
                           await _consented(db, user.id, {"aktuell": data, "vorher": prev}), json_mode=True, max_tokens=3000)
    if text:
        try:
            parsed = parse_json(text)
            if isinstance(parsed, dict) and "summary" in parsed:
                report = {**report, **parsed, "generated_by": "ai"}
        except ValueError:
            log.warning("Bericht-JSON nicht lesbar")
    return await _store(db, user.id, period, start, report.get("summary", ""), {"report": report, "metrics": jsonable(data)})


async def run_weekly(db: AsyncSession, user: User) -> CoachSummary:
    start = st.week_start(date.today()) - timedelta(days=7)
    row = await period_report(db, user, "week", start)
    await _hint(db, user, "weekly", "Dein Wochenrückblick ist da 📊", row.content[:180], {"start": start.isoformat()},
                f"weekly:{start}", push_kind="briefings", url=f"/progress/report?period=week&start={start}")
    return row


async def run_monthly(db: AsyncSession, user: User) -> CoachSummary:
    start = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    return await period_report(db, user, "month", start)


# ---------------------------------------------------------------- proaktive Hinweise
async def _hint(db: AsyncSession, user: User, kind: str, title: str, body: str, data: dict[str, Any], dedupe: str,
                push_kind: str = "hints", url: str = "/coach") -> CoachHint | None:
    if (await db.exec(select(CoachHint).where(CoachHint.user_id == user.id, CoachHint.dedupe_key == dedupe))).first():
        return None
    h = CoachHint(user_id=user.id, kind=kind, title=title, body=body, data=jsonable(data), dedupe_key=dedupe)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    await notify_user(db, user.id, title, body, url=url, kind=push_kind, tag=kind)
    return h


async def detect_hints(db: AsyncSession, user: User) -> list[CoachHint]:
    s = await get_user_settings(db, user.id)
    pro = s["ai"].get("proactive", {})
    if not pro.get("enabled", True):
        return []
    today = date.today()
    iso_week = f"{today.isocalendar()[0]}-{today.isocalendar()[1]}"
    created: list[CoachHint | None] = []

    if pro.get("protein_low"):
        nut = await st.nutrition_stats(db, user.id, today - timedelta(days=3), today - timedelta(days=1))
        days = [d for d in nut["days"] if d["logged"]]
        if len(days) >= 3 and all(d["protein"] < d["target_protein"] * 0.9 for d in days):
            avg = round(sum(d["protein"] for d in days) / len(days))
            created.append(await _hint(db, user, "protein_low", "Protein unter Ziel",
                                       f"Du lagst 3 Tage in Folge unter deinem Proteinziel (Ø {avg} g). "
                                       "Ein Quark, Skyr oder Shake bringt schnell 30–40 g.", {"avg": avg}, f"protein:{today}"))

    if pro.get("missed_training"):
        plan = (await db.exec(select(Plan).where(Plan.owner_id == user.id, Plan.is_active))).first()
        last = (await db.exec(select(Workout).where(Workout.user_id == user.id).order_by(Workout.started_at.desc()).limit(1))).first()
        if plan:
            days_since = (today - st.local_date(last.started_at)).days if last else 99
            if days_since >= 5:
                created.append(await _hint(db, user, "missed_training", "Zeit fürs nächste Training 💪",
                                           f"Dein letztes Training ist {days_since if days_since < 99 else 'lange'} Tage her. "
                                           "Schon eine kurze Einheit hält den Fortschritt am Laufen.",
                                           {"days": days_since}, f"missed:{iso_week}"))

    if pro.get("plateau"):
        from app.models import WorkoutSet

        rows = (await db.exec(select(WorkoutSet.exercise_id).where(WorkoutSet.user_id == user.id).distinct())).all()
        for eid in rows[:40]:
            prog = await st.exercise_progress(db, user.id, eid, today - timedelta(days=56), today)
            sess = prog["sessions"]
            if len(sess) >= 5:
                recent = max(x["e1rm"] for x in sess[-3:])
                earlier = max(x["e1rm"] for x in sess[:-3])
                if recent <= earlier:
                    from app.models import Exercise

                    ex = await db.get(Exercise, eid)
                    created.append(await _hint(
                        db, user, "plateau", f"Plateau bei {ex.name if ex else 'einer Übung'}",
                        "Seit 3 Einheiten keine Steigerung des geschätzten 1RM. Optionen: Wiederholungsbereich wechseln, "
                        "Variante tauschen oder eine leichtere Woche einlegen.",
                        {"exercise_id": eid, "e1rm": recent}, f"plateau:{eid}:{iso_week}"))
                    break

    if pro.get("deload"):
        rows = await st._sets_in_range(db, user.id, today - timedelta(days=14), today)
        rpes = [s.rpe for s, _ in rows if s.rpe]
        n_workouts = len({s.workout_id for s, _ in rows})
        if len(rpes) >= 20 and n_workouts >= 6 and sum(rpes) / len(rpes) >= 9:
            created.append(await _hint(db, user, "deload", "Deload empfohlen",
                                       f"Deine durchschnittliche RPE lag in 2 Wochen bei {sum(rpes) / len(rpes):.1f}. "
                                       "Eine Woche mit ~40 % weniger Sätzen hilft der Regeneration.",
                                       {"avg_rpe": round(sum(rpes) / len(rpes), 1)}, f"deload:{iso_week}"))
    return [h for h in created if h]


# ---------------------------------------------------------------- Briefings
async def briefing(db: AsyncSession, user: User, kind: str) -> CoachHint | None:
    from app.api.training import next_plan_day

    today = date.today()
    s = await get_user_settings(db, user.id)
    targets = await user_targets(db, user.id)
    plan = await next_plan_day(db, user.id)
    if kind == "morning":
        data = {"targets_today": targets["today"], "day_type": targets["day_type"], "plan": plan}
        fallback = (f"Heute ist {'Trainingstag' if targets['day_type'] == 'training' else 'Ruhetag'}. "
                    f"Ziel: {targets['today']['kcal']:.0f} kcal, {targets['today']['protein']:.0f} g Protein."
                    + (f" Geplant: {plan['day']['name']}." if plan and not plan["rest_day"] else ""))
        instr = "Schreibe ein kurzes Morgen-Briefing (max. 3 Sätze, motivierend): Was steht heute an, worauf achten?"
        title = "Guten Morgen ☀️"
    else:
        from app.services.meals import day_summary

        day = await day_summary(db, user.id, today, s["meal_slots"])
        data = {"totals": day["totals"], "targets": day["targets"], "water_ml": day["water_ml"], "plan": plan}
        rest_p = max(0, day["targets"]["protein"] - day["totals"]["protein"])
        fallback = (f"Heute: {day['totals']['kcal']:.0f}/{day['targets']['kcal']:.0f} kcal, "
                    f"{day['totals']['protein']:.0f}/{day['targets']['protein']:.0f} g Protein."
                    + (f" Noch {rest_p:.0f} g Protein offen." if rest_p > 15 else " Stark gemacht!"))
        instr = "Schreibe einen kurzen Abend-Check-in (max. 3 Sätze): Bilanz des Tages und ein Tipp für den Abend/morgen."
        title = "Abend-Check-in 🌙"
    text = await _llm_text(db, user, "briefing", instr, await _consented(db, user.id, data), max_tokens=500) or fallback
    return await _hint(db, user, "briefing" if kind == "morning" else "checkin", title, text.strip(), data,
                       f"{kind}:{today}", push_kind="briefings", url="/")
