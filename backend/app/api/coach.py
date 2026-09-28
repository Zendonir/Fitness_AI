import asyncio
import base64
import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import select

from app.ai.actions import execute_action
from app.ai.client import ai_available, parse_json, run_llm
from app.ai.context import build_system_prompt, jsonable
from app.ai.providers.base import Message, ProviderError
from app.ai.registry import PROVIDERS, TASKS, provider_chain, resolve_credentials
from app.ai.tools import TOOL_SPECS, execute_tool, make_context
from app.ai.usage import AIDisabledError, AILimitError, month_cost, user_limit
from app.api.body import process_image
from app.core.access import get_owned
from app.core.config import settings
from app.core.deps import DB, CurrentUser
from app.core.security import decrypt, encrypt, mask_secret
from app.models import (
    ChatConversation,
    ChatMessage,
    CoachHint,
    CoachNote,
    CoachProfile,
    CoachSummary,
    Exercise,
    MealPlan,
    PendingAction,
    PushSubscription,
    Recipe,
    UserAIKey,
)
from app.services import stats as st
from app.services.app_settings import get_user_settings
from app.services.push import notify_user, push_configured

log = logging.getLogger(__name__)
router = APIRouter(prefix="/coach", tags=["coach"])
push_router = APIRouter(prefix="/push", tags=["push"])

HISTORY_MESSAGES = 12


def _ai_error(e: Exception) -> HTTPException:
    if isinstance(e, AILimitError):
        return HTTPException(402, str(e))
    if isinstance(e, AIDisabledError):
        return HTTPException(409, str(e))
    return HTTPException(502, f"KI-Anfrage fehlgeschlagen: {e}")


# ================================================================ Status & Einstellungen
@router.get("/status")
async def status(user: CurrentUser, db: DB) -> dict[str, Any]:
    ok, reason = await ai_available(db, user)
    s = await get_user_settings(db, user.id)
    providers = {}
    for name in PROVIDERS:
        key, url, source = await resolve_credentials(db, user.id, name)
        providers[name] = {"configured": bool(url) if name == "ollama" else bool(key), "source": source}
    chain = await provider_chain(db, user.id, s["ai"], "chat")
    return {"available": ok, "reason": reason, "providers": providers,
            "active": {"provider": chain[0].name, "model": chain[0].model} if chain else None,
            "month_cost_usd": round(await month_cost(db, user.id), 4), "limit_usd": await user_limit(db, user),
            "tasks": TASKS, "push_configured": push_configured()}


@router.get("/models")
async def models(provider: str, user: CurrentUser, db: DB) -> list[str]:
    if provider not in PROVIDERS:
        raise HTTPException(404, "Unbekannter Provider")
    key, url, _ = await resolve_credentials(db, user.id, provider)
    try:
        return await PROVIDERS[provider](api_key=key, base_url=url).list_models()
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e


class KeyIn(BaseModel):
    provider: str = Field(pattern="^(anthropic|openai)$")
    key: str


@router.get("/keys")
async def get_keys(user: CurrentUser, db: DB) -> dict[str, str]:
    rows = (await db.exec(select(UserAIKey).where(UserAIKey.user_id == user.id))).all()
    return {r.provider: mask_secret(decrypt(r.key_enc)) for r in rows}


@router.put("/keys")
async def put_key(body: KeyIn, user: CurrentUser, db: DB) -> dict[str, bool]:
    row = (await db.exec(select(UserAIKey).where(UserAIKey.user_id == user.id, UserAIKey.provider == body.provider))).first()
    if not body.key:
        if row:
            await db.delete(row)
            await db.commit()
        return {"ok": True}
    row = row or UserAIKey(user_id=user.id, provider=body.provider, key_enc="")
    row.key_enc = encrypt(body.key.strip())
    db.add(row)
    await db.commit()
    return {"ok": True}


# ================================================================ Coach-Profil & Gedächtnis
class CoachProfileIn(BaseModel):
    goals: str | None = None
    experience: str | None = None
    preferences: str | None = None
    dislikes: str | None = None
    limitations: str | None = None
    equipment: str | None = None
    schedule: str | None = None


@router.get("/profile")
async def get_profile(user: CurrentUser, db: DB) -> dict[str, Any]:
    cp = await db.get(CoachProfile, user.id) or CoachProfile(user_id=user.id)
    return cp.model_dump()


@router.put("/profile")
async def put_profile(body: CoachProfileIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    cp = await db.get(CoachProfile, user.id) or CoachProfile(user_id=user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(cp, k, v or "")
    cp.updated_at = datetime.now(UTC)
    db.add(cp)
    await db.commit()
    return cp.model_dump()


@router.delete("/profile")
async def reset_profile(user: CurrentUser, db: DB) -> dict[str, bool]:
    cp = await db.get(CoachProfile, user.id)
    if cp:
        await db.delete(cp)
    db.add(CoachProfile(user_id=user.id))
    await db.commit()
    return {"ok": True}


class NoteIn(BaseModel):
    content: str = Field(max_length=500)
    category: str = "general"
    importance: int = Field(2, ge=1, le=3)


@router.get("/notes")
async def list_notes(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(CoachNote).where(CoachNote.user_id == user.id).order_by(CoachNote.created_at.desc()))).all()
    return [r.model_dump() for r in rows]


@router.post("/notes")
async def add_note(body: NoteIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    n = CoachNote(user_id=user.id, source="user", **body.model_dump())
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return n.model_dump()


@router.patch("/notes/{nid}")
async def patch_note(nid: int, body: NoteIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    n = await get_owned(db, CoachNote, nid, user.id)
    for k, v in body.model_dump().items():
        setattr(n, k, v)
    db.add(n)
    await db.commit()
    return n.model_dump()


@router.delete("/notes/{nid}")
async def delete_note(nid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    n = await get_owned(db, CoachNote, nid, user.id)
    await db.delete(n)
    await db.commit()
    return {"ok": True}


@router.delete("/memory")
async def wipe_memory(user: CurrentUser, db: DB) -> dict[str, bool]:
    for model in (CoachNote, CoachSummary):
        for r in (await db.exec(select(model).where(model.user_id == user.id))).all():
            await db.delete(r)
    await db.commit()
    return {"ok": True}


@router.get("/summaries")
async def list_summaries(user: CurrentUser, db: DB, period: str | None = None) -> list[dict[str, Any]]:
    stmt = select(CoachSummary).where(CoachSummary.user_id == user.id).order_by(CoachSummary.period_start.desc()).limit(60)
    if period:
        stmt = stmt.where(CoachSummary.period == period)
    return [r.model_dump() for r in (await db.exec(stmt)).all()]


@router.delete("/summaries/{sid}")
async def delete_summary(sid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    s = await get_owned(db, CoachSummary, sid, user.id)
    await db.delete(s)
    await db.commit()
    return {"ok": True}


# ================================================================ Unterhaltungen
@router.get("/conversations")
async def list_conversations(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(ChatConversation).where(ChatConversation.user_id == user.id)
                          .order_by(ChatConversation.updated_at.desc()).limit(100))).all()
    return [r.model_dump() for r in rows]


@router.get("/conversations/{cid}")
async def get_conversation(cid: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    c = await get_owned(db, ChatConversation, cid, user.id)
    msgs = (await db.exec(select(ChatMessage).where(ChatMessage.conversation_id == c.id).order_by(ChatMessage.created_at))).all()
    actions = (await db.exec(select(PendingAction).where(PendingAction.conversation_id == c.id))).all()
    return {**c.model_dump(), "messages": [m.model_dump() for m in msgs], "actions": [a.model_dump() for a in actions]}


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    c = await get_owned(db, ChatConversation, cid, user.id)
    await db.delete(c)
    await db.commit()
    return {"ok": True}


QUICK_ACTIONS = {
    "dinner": "Was esse ich heute Abend? Berücksichtige meine Restmakros für heute, meine Vorlieben und vorhandene Rezepte.",
    "week": "Wie war meine Woche? Bewerte Training, Ernährung und Fortschritt und gib mir 2–3 konkrete Tipps.",
    "short_workout": "Passe mein heutiges Training an, ich habe nur 30 Minuten. Schlage ein konkretes Workout vor.",
    "plan_review": "Analysiere meinen Fortschritt (Progression, RPE, Regeneration, Trainingsfrequenz) der letzten Wochen "
                   "und schlage bei Bedarf konkrete Anpassungen meines aktiven Plans vor.",
}


class ChatIn(BaseModel):
    message: str = ""
    conversation_id: int | None = None
    quick_action: str | None = None
    exercise_id: int | None = None  # für Formcheck
    image: str | None = None  # base64 (ohne data:-Präfix)
    image_type: str = "image/jpeg"


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable(data), ensure_ascii=False, default=str)}\n\n"


@router.post("/chat")
async def chat(body: ChatIn, user: CurrentUser, db: DB) -> StreamingResponse:
    """Streaming-Chat (Server-Sent Events): meta, text, tool, action, fallback, done, error."""
    ok, reason = await ai_available(db, user)
    if not ok:
        raise HTTPException(409, reason)
    text = body.message.strip()
    if body.quick_action in QUICK_ACTIONS:
        text = QUICK_ACTIONS[body.quick_action] + (f"\n{text}" if text else "")
    extra = ""
    if body.quick_action == "formcheck" and body.exercise_id:
        ex = await db.get(Exercise, body.exercise_id)
        if ex:
            extra = (f"## Formcheck\nDer Benutzer beschreibt Probleme bei „{ex.name}“ (Hauptmuskeln: {', '.join(ex.primary_muscles)}). "
                     "Gib konkrete Technik-Hinweise (Cues), mögliche Ursachen und 2–3 Alternativübungen. "
                     "Bei Schmerzen: ärztliche/physiotherapeutische Abklärung empfehlen.")
            text = f"Formcheck {ex.name}: {text}"
    if not text and not body.image:
        raise HTTPException(422, "Nachricht fehlt")
    s = await get_user_settings(db, user.id)
    if body.image and not s["ai"]["consents"].get("photos"):
        raise HTTPException(403, "Fotos sind nicht für die KI freigegeben (Einstellungen → KI → Datenfreigaben)")

    if body.conversation_id:
        conv = await get_owned(db, ChatConversation, body.conversation_id, user.id)
    else:
        conv = ChatConversation(user_id=user.id, title=(text[:60] or "Foto"))
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    history = (await db.exec(select(ChatMessage).where(ChatMessage.conversation_id == conv.id)
                             .order_by(ChatMessage.created_at.desc()).limit(HISTORY_MESSAGES))).all()[::-1]
    db.add(ChatMessage(conversation_id=conv.id, user_id=user.id, role="user", content=text,
                       meta={"quick_action": body.quick_action, "has_image": bool(body.image)}))
    await db.commit()

    messages = [Message(m.role, m.content) for m in history if m.content]
    images = [{"media_type": body.image_type, "data": body.image}] if body.image else []
    messages.append(Message("user", text or "Was siehst du auf dem Foto?", images))

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def worker() -> None:
        from app.core.db import session_scope

        async with session_scope() as wdb:
            wuser = await wdb.get(type(user), user.id)
            ctx = await make_context(wdb, wuser, conv.id)
            try:
                system = await build_system_prompt(wdb, wuser, extra)

                async def on_text(t: str) -> None:
                    await queue.put(_sse("text", {"delta": t}))

                async def on_event(kind: str, data: dict[str, Any]) -> None:
                    await queue.put(_sse(kind, data))

                async def executor(call):
                    before = len(ctx.pending)
                    out = await execute_tool(ctx, call)
                    for pa in ctx.pending[before:]:
                        await queue.put(_sse("action", pa.model_dump()))
                    return out

                res = await run_llm(wdb, wuser, "chat", system, messages, TOOL_SPECS, executor, on_text, on_event,
                                    max_tokens=16000)
                msg = ChatMessage(conversation_id=conv.id, user_id=user.id, role="assistant", content=res.text,
                                  meta={"provider": res.provider, "model": res.model, "tools": res.tool_calls,
                                        "actions": [p.id for p in ctx.pending], "fallback": res.fallback_used})
                wdb.add(msg)
                c = await wdb.get(ChatConversation, conv.id)
                c.updated_at = datetime.now(UTC)
                wdb.add(c)
                await wdb.commit()
                await wdb.refresh(msg)
                await queue.put(_sse("done", {"message_id": msg.id, "provider": res.provider, "model": res.model}))
            except (AIDisabledError, AILimitError, ProviderError) as e:
                await queue.put(_sse("error", {"message": str(e)}))
            except Exception as e:  # noqa: BLE001
                log.exception("Chat fehlgeschlagen")
                await queue.put(_sse("error", {"message": f"Interner Fehler: {e}"}))
            finally:
                await queue.put(None)

    async def stream():
        yield _sse("meta", {"conversation_id": conv.id})
        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            await task

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ================================================================ Bestätigungen
@router.get("/actions")
async def list_actions(user: CurrentUser, db: DB, status: str = "pending") -> list[dict[str, Any]]:
    rows = (await db.exec(select(PendingAction).where(PendingAction.user_id == user.id, PendingAction.status == status)
                          .order_by(PendingAction.created_at.desc()).limit(50))).all()
    return [r.model_dump() for r in rows]


@router.post("/actions/{aid}/confirm")
async def confirm_action(aid: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    pa = await get_owned(db, PendingAction, aid, user.id)
    return {"status": "confirmed", "result": await execute_action(db, user, pa)}


@router.post("/actions/{aid}/reject")
async def reject_action(aid: int, user: CurrentUser, db: DB) -> dict[str, str]:
    pa = await get_owned(db, PendingAction, aid, user.id)
    if pa.status != "pending":
        raise HTTPException(409, "Aktion wurde bereits bearbeitet")
    pa.status, pa.resolved_at = "rejected", datetime.now(UTC)
    db.add(pa)
    await db.commit()
    return {"status": "rejected"}


# ================================================================ Hinweise
@router.get("/hints")
async def list_hints(user: CurrentUser, db: DB, include_dismissed: bool = False) -> list[dict[str, Any]]:
    stmt = select(CoachHint).where(CoachHint.user_id == user.id).order_by(CoachHint.created_at.desc()).limit(50)
    if not include_dismissed:
        stmt = stmt.where(~CoachHint.dismissed)  # type: ignore[operator]
    return [r.model_dump() for r in (await db.exec(stmt)).all()]


@router.post("/hints/{hid}/read")
async def read_hint(hid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    h = await get_owned(db, CoachHint, hid, user.id)
    h.read_at = h.read_at or datetime.now(UTC)
    db.add(h)
    await db.commit()
    return {"ok": True}


@router.post("/hints/{hid}/dismiss")
async def dismiss_hint(hid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    h = await get_owned(db, CoachHint, hid, user.id)
    h.dismissed = True
    db.add(h)
    await db.commit()
    return {"ok": True}


@router.post("/hints/check")
async def check_hints(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    from app.ai.jobs import detect_hints

    return [h.model_dump() for h in await detect_hints(db, user)]


# ================================================================ Berichte / Zusammenfassungen auf Abruf
@router.post("/reports/{period}")
async def generate_report(period: str, user: CurrentUser, db: DB, start: date | None = None) -> dict[str, Any]:
    from app.ai.jobs import period_report

    if period == "week":
        s = st.week_start(start or date.today() - timedelta(days=7))
    elif period == "month":
        s = (start or (date.today().replace(day=1) - timedelta(days=1))).replace(day=1)
    else:
        raise HTTPException(404, "Unbekannter Zeitraum")
    return (await period_report(db, user, period, s)).model_dump()


# ================================================================ Foto-Erkennung
VISION_MEAL = """Analysiere das Foto einer Mahlzeit. Schätze die enthaltenen Lebensmittel und Mengen.
Antworte NUR mit JSON: {"items":[{"name":"…","grams":Zahl,"kcal":Zahl,"protein":Zahl,"carbs":Zahl,"fat":Zahl,"fiber":Zahl,
"confidence":"hoch|mittel|niedrig"}],"note":"kurzer Hinweis"}. Nährwerte absolut für die geschätzte Menge."""

VISION_LABEL = """Lies das Nährwertetikett auf dem Foto ab. Antworte NUR mit JSON:
{"name":"Produktname oder leer","brand":"","kcal":Zahl,"protein":Zahl,"carbs":Zahl,"sugar":Zahl,"fat":Zahl,"sat_fat":Zahl,
"fiber":Zahl,"salt":Zahl,"serving_g":Zahl oder null}. Alle Werte pro 100 g bzw. 100 ml. kJ in kcal umrechnen falls nötig."""


async def _vision(db: DB, user: CurrentUser, file: UploadFile, prompt: str, note: str = "") -> dict[str, Any]:
    s = await get_user_settings(db, user.id)
    if not s["ai"]["consents"].get("photos"):
        raise HTTPException(403, "Fotos sind nicht für die KI freigegeben (Einstellungen → KI → Datenfreigaben)")
    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(413, "Foto zu groß")
    img = base64.b64encode(await asyncio.to_thread(process_image, raw, 1280)).decode()
    try:
        res = await run_llm(db, user, "vision", "Du bist ein präziser Ernährungsassistent. Antworte ausschließlich mit JSON.",
                            [Message("user", prompt + (f"\nHinweis des Benutzers: {note}" if note else ""),
                                     [{"media_type": "image/jpeg", "data": img}])], max_tokens=2000, json_mode=True)
        return {"result": parse_json(res.text), "provider": res.provider, "model": res.model}
    except ValueError as e:
        raise HTTPException(422, "Die KI-Antwort konnte nicht gelesen werden – bitte erneut versuchen") from e
    except (AIDisabledError, AILimitError, ProviderError) as e:
        raise _ai_error(e) from e


@router.post("/vision/meal")
async def vision_meal(user: CurrentUser, db: DB, file: UploadFile = File(...), note: str = Form("")) -> dict[str, Any]:
    return await _vision(db, user, file, VISION_MEAL, note)


@router.post("/vision/label")
async def vision_label(user: CurrentUser, db: DB, file: UploadFile = File(...)) -> dict[str, Any]:
    return await _vision(db, user, file, VISION_LABEL)


# ================================================================ Mahlzeitenplanung
class MealPlanIn(BaseModel):
    days: int = Field(7, ge=1, le=7)
    notes: str = ""
    today_only: bool = False


MEAL_PLAN_PROMPT = """Erstelle einen {what} passend zu den Tageszielen, Vorlieben/Abneigungen und vorhandenen Rezepten.
Verwende bevorzugt die vorhandenen Rezepte (per Name), sonst einfache Gerichte. Halte die Makroziele (±10 %) ein und
unterschreite nie die Untergrenzen. Antworte NUR mit JSON:
{{"days":[{{"day":"Montag","meals":[{{"slot":"Frühstück","name":"…","recipe":"Rezeptname oder null",
"ingredients":[{{"name":"…","grams":Zahl}}],"kcal":Zahl,"protein":Zahl,"carbs":Zahl,"fat":Zahl}}],
"totals":{{"kcal":Zahl,"protein":Zahl}}}}],
"shopping_list":[{{"name":"…","amount":"z. B. 500 g","category":"Obst & Gemüse|Kühlregal|Fleisch & Fisch|Vorrat|Sonstiges"}}],
"tips":["…"]}}"""


@router.post("/meal-plan")
async def create_meal_plan(body: MealPlanIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    from app.services.meals import day_summary, recipe_nutrition
    from app.services.targets import user_targets
    from app.core.access import readable_clause

    s = await get_user_settings(db, user.id)
    targets = await user_targets(db, user.id)
    recipes = (await db.exec(select(Recipe).where(readable_clause(Recipe, "recipe", user.id)).limit(40))).all()
    data: dict[str, Any] = {
        "ziele": {"training": targets["training"], "rest": targets["rest"], "untergrenzen": targets["floors"]},
        "mahlzeiten_slots": s["meal_slots"],
        "rezepte": [{"name": r.name, **(await recipe_nutrition(db, r))["per_serving"]} for r in recipes],
        "wünsche": body.notes,
    }
    if body.today_only:
        data["heute_bereits_gegessen"] = (await day_summary(db, user.id, date.today(), s["meal_slots"]))["totals"]
    what = "Plan für den Rest des heutigen Tages (nur ein Tag, Restmakros)" if body.today_only else f"Wochenplan für {body.days} Tage mit Einkaufsliste"
    try:
        system = await build_system_prompt(db, user)
        res = await run_llm(db, user, "meal_plan", system,
                            [Message("user", MEAL_PLAN_PROMPT.format(what=what) + "\n\nDaten:\n" + json.dumps(jsonable(data), ensure_ascii=False))],
                            max_tokens=12000, json_mode=True)
        plan = parse_json(res.text)
    except ValueError as e:
        raise HTTPException(422, "Plan konnte nicht gelesen werden – bitte erneut versuchen") from e
    except (AIDisabledError, AILimitError, ProviderError) as e:
        raise _ai_error(e) from e
    mp = MealPlan(user_id=user.id, week_start=st.week_start(date.today()), plan=plan,
                  shopping_list=plan.get("shopping_list", []) if isinstance(plan, dict) else [])
    db.add(mp)
    await db.commit()
    await db.refresh(mp)
    return mp.model_dump()


@router.get("/meal-plans")
async def list_meal_plans(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(MealPlan).where(MealPlan.user_id == user.id).order_by(MealPlan.created_at.desc()).limit(10))).all()
    return [r.model_dump() for r in rows]


@router.delete("/meal-plans/{mid}")
async def delete_meal_plan(mid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    m = await get_owned(db, MealPlan, mid, user.id)
    await db.delete(m)
    await db.commit()
    return {"ok": True}


# ================================================================ Push
class SubscriptionIn(BaseModel):
    endpoint: str
    keys: dict[str, str]


@push_router.get("/config")
async def push_config() -> dict[str, Any]:
    return {"enabled": push_configured(), "public_key": settings.vapid_public_key}


@push_router.post("/subscribe")
async def subscribe(body: SubscriptionIn, user: CurrentUser, db: DB) -> dict[str, bool]:
    row = (await db.exec(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))).first()
    row = row or PushSubscription(user_id=user.id, endpoint=body.endpoint, p256dh="", auth="")
    row.user_id, row.p256dh, row.auth = user.id, body.keys.get("p256dh", ""), body.keys.get("auth", "")
    db.add(row)
    await db.commit()
    return {"ok": True}


@push_router.post("/unsubscribe")
async def unsubscribe(body: SubscriptionIn, user: CurrentUser, db: DB) -> dict[str, bool]:
    row = (await db.exec(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint,
                                                        PushSubscription.user_id == user.id))).first()
    if row:
        await db.delete(row)
        await db.commit()
    return {"ok": True}


@push_router.post("/test")
async def test_push(user: CurrentUser, db: DB) -> dict[str, int]:
    return {"sent": await notify_user(db, user.id, "FitForge", "Push funktioniert! 🎉", kind="hints", tag="test")}


class TimerIn(BaseModel):
    seconds: int = Field(ge=5, le=1800)
    exercise: str = ""


@push_router.post("/timer")
async def timer_push(body: TimerIn, user: CurrentUser) -> dict[str, Any]:
    """Pausen-Timer: Push nach Ablauf – auch wenn die App im Hintergrund ist.
    Ein neuer Timer ersetzt den alten (Token in Redis), Abbrechen löscht das Token."""
    import secrets

    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        token = secrets.token_hex(8)
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.set(f"ff:timer:{user.id}", token, ex=body.seconds + 120)
        await pool.enqueue_job("timer_push_job", user.id, token, body.exercise, _defer_by=timedelta(seconds=body.seconds))
        await pool.aclose()
        return {"scheduled": True}
    except Exception as e:  # noqa: BLE001
        log.warning("Timer-Push nicht planbar: %s", e)
        return {"scheduled": False}


@push_router.delete("/timer")
async def cancel_timer(user: CurrentUser) -> dict[str, bool]:
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.delete(f"ff:timer:{user.id}")
        await pool.aclose()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}
