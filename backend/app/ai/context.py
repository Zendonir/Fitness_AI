"""Kontextaufbau pro Anfrage: Systemprompt + Profil + Notizen + Zusammenfassungen + Tagesstand – im Token-Budget."""

from datetime import date, timedelta
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models import CoachNote, CoachProfile, CoachSummary, PromptTemplate, User, UserProfile
from app.seed.prompts import COACH_SYSTEM_PROMPT, STYLE_TEXT
from app.services.app_settings import get_user_settings
from app.services.nutrition import body_from_profile, floors
from app.services.targets import latest_weight

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


async def active_prompt(db: AsyncSession, name: str = "coach_system") -> str:
    row = (await db.exec(select(PromptTemplate).where(PromptTemplate.name == name, PromptTemplate.is_active))).first()
    return row.content if row else COACH_SYSTEM_PROMPT


def _profile_block(cp: CoachProfile | None) -> str:
    if not cp:
        return ""
    labels = [("goals", "Ziele"), ("experience", "Erfahrung"), ("preferences", "Vorlieben"), ("dislikes", "Abneigungen"),
              ("limitations", "Einschränkungen"), ("equipment", "Equipment"), ("schedule", "Trainingszeiten")]
    lines = [f"- {label}: {getattr(cp, k)}" for k, label in labels if getattr(cp, k)]
    return "## Coach-Profil\n" + "\n".join(lines) if lines else ""


async def build_system_prompt(db: AsyncSession, user: User, extra: str = "") -> str:
    s = await get_user_settings(db, user.id)
    ai = s["ai"]
    consents = ai.get("consents", {})
    profile = await db.get(UserProfile, user.id) or UserProfile(user_id=user.id)
    body = body_from_profile(profile, await latest_weight(db, user.id))
    fl = floors(body)
    today = date.today()
    base = (await active_prompt(db)).format_map(_SafeDict(
        name=user.display_name or "der Benutzer",
        style=STYLE_TEXT.get((ai.get("style_length", "short"), ai.get("style_tone", "motivating")), ""),
        kcal_floor=int(fl["kcal"]), protein_floor=int(fl["protein"]),
        today=f"{WEEKDAYS[today.weekday()]}, {today.strftime('%d.%m.%Y')}",
    ))
    budget = settings.ai_context_token_budget - estimate_tokens(base) - estimate_tokens(extra)
    parts: list[str] = []

    def add(block: str) -> bool:
        nonlocal budget
        t = estimate_tokens(block)
        if not block or t > budget:
            return False
        parts.append(block)
        budget -= t
        return True

    add(_profile_block(await db.get(CoachProfile, user.id)))
    facts = [f"- Ziel: {({'bulk': 'Aufbau', 'maintain': 'Erhalt', 'cut': 'moderates Defizit'})[body.goal]}",
             f"- Trainingstage/Woche: {body.training_days_per_week}"]
    if consents.get("body"):
        facts += [f"- Geschlecht: {'männlich' if body.sex == 'male' else 'weiblich'}, Alter {body.age}, "
                  f"Größe {body.height_cm:g} cm, Gewicht {body.weight_kg:g} kg"]
    else:
        facts.append("- Körperwerte: nicht freigegeben (nicht danach fragen, außer der Benutzer bringt sie selbst ein)")
    denied = [k for k, v in consents.items() if not v]
    if denied:
        facts.append(f"- Nicht freigegebene Datenkategorien: {', '.join(denied)}")
    add("## Basisdaten\n" + "\n".join(facts))

    notes = (await db.exec(select(CoachNote).where(CoachNote.user_id == user.id)
                           .order_by(CoachNote.importance.desc(), CoachNote.created_at.desc()).limit(60))).all()
    if notes:
        header, lines = "## Gedächtnis (Notizen)", []
        for n in notes:
            line = f"- [{n.category}] {n.content} ({n.created_at.strftime('%d.%m.%y')})"
            if estimate_tokens("\n".join([header, *lines, line])) > min(budget, 2500):
                break
            lines.append(line)
        add(header + "\n" + "\n".join(lines))

    summaries = (await db.exec(select(CoachSummary).where(CoachSummary.user_id == user.id)
                               .order_by(CoachSummary.period_start.desc()).limit(20))).all()
    chosen: list[CoachSummary] = []
    for period, n in (("day", 3), ("week", 2), ("month", 1)):
        chosen += [x for x in summaries if x.period == period][:n]
    if chosen:
        label = {"day": "Tag", "week": "Woche ab", "month": "Monat"}
        add("## Verlauf (Zusammenfassungen)\n" + "\n".join(
            f"- {label[x.period]} {x.period_start.strftime('%d.%m.%Y')}: {x.content[:600]}" for x in chosen))
    if extra:
        parts.append(extra)
    return base + "\n\n" + "\n\n".join(parts)


def since(days: int) -> date:
    return date.today() - timedelta(days=days)


def jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [jsonable(x) for x in v]
    if isinstance(v, date):
        return v.isoformat()
    return v
