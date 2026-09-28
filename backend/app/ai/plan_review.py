"""Plan-Review: Der Coach prüft einen Plan und schlägt Änderungen vor (auf Anfrage oder proaktiv)."""

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.client import run_llm
from app.ai.context import build_system_prompt
from app.ai.providers.base import Message
from app.ai.tools import TOOL_SPECS, execute_tool, make_context
from app.models import PendingAction, Plan, User

PLAN_TOOLS = {"get_active_plan", "list_plans", "get_plan", "get_workouts", "get_exercise_progress", "get_personal_records",
              "get_training_volume", "search_exercises", "save_memory", "propose_plan_changes", "propose_new_plan"}

USER_REQUEST = """Bearbeite meinen Trainingsplan „{plan}“ nach diesem Wunsch: {request}
Lade zuerst den Plan und meine letzten Trainings, dann schlage die Änderungen mit propose_plan_changes vor
(oder propose_new_plan, falls ein komplett neuer Plan sinnvoller ist). Erkläre danach kurz, was du geändert hast und warum."""

PROACTIVE_REVIEW = """Prüfe meinen aktiven Trainingsplan „{plan}“ anhand meiner Trainings der letzten Wochen
(Progression/1RM-Verlauf, RPE, Volumen pro Muskelgruppe, Trainingsfrequenz, ausgelassene Einheiten, Regeneration).
Schlage NUR dann Änderungen mit propose_plan_changes vor, wenn es einen klaren, datenbasierten Grund gibt
(z. B. Plateau, dauerhaft zu hohe RPE, Muskelgruppe unter-/übertrainiert, Einheiten regelmäßig ausgelassen, Deload fällig).
Maximal 3–5 gezielte Änderungen. Wenn alles passt, schlage nichts vor und antworte nur mit „Keine Änderung nötig“ und einem Satz Begründung."""


async def run_plan_review(db: AsyncSession, user: User, plan: Plan | None, request: str | None,
                          proactive: bool = False) -> dict[str, Any]:
    ctx = await make_context(db, user)
    ctx.allowed = PLAN_TOOLS
    name = plan.name if plan else "aktiver Plan"
    prompt = PROACTIVE_REVIEW.format(plan=name) if proactive else USER_REQUEST.format(plan=name, request=request or
                                                                                      "Optimiere ihn auf Basis meines Fortschritts.")
    system = await build_system_prompt(db, user)
    tools = [t for t in TOOL_SPECS if t.name in PLAN_TOOLS]

    async def executor(call):
        if call.name == "propose_plan_changes" and plan and not call.arguments.get("plan"):
            call.arguments["plan"] = plan.name
        return await execute_tool(ctx, call)

    res = await run_llm(db, user, "plan_review", system, [Message("user", prompt)], tools, executor, max_tokens=8000, max_rounds=8)
    return {"text": res.text, "provider": res.provider, "model": res.model, "actions": [jsonable_action(p) for p in ctx.pending]}


def jsonable_action(p: PendingAction) -> dict[str, Any]:
    return p.model_dump()
