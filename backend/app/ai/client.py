"""Zentrale LLM-Ausführung: Freigaben, Limit, Provider-Fallback, Tool-Schleife, Protokollierung."""

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.providers.base import Message, ProviderError, TextCallback, ToolCall, ToolSpec
from app.ai.registry import provider_chain
from app.ai.usage import AIDisabledError, check_limit, record_usage
from app.models import User
from app.services.app_settings import get_user_settings, system_flags

log = logging.getLogger(__name__)

ToolExecutor = Callable[[ToolCall], Awaitable[str]]
EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]] | None


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    fallback_used: bool = False


async def ai_available(db: AsyncSession, user: User) -> tuple[bool, str]:
    flags = await system_flags(db)
    if not flags["ai_enabled"]:
        return False, "KI-Funktionen sind vom Administrator deaktiviert."
    s = await get_user_settings(db, user.id)
    if not s["ai"].get("enabled", True):
        return False, "KI-Funktionen sind in deinen Einstellungen deaktiviert."
    if not await provider_chain(db, user.id, s["ai"], "chat"):
        return False, "Kein KI-Provider konfiguriert."
    return True, ""


async def run_llm(
    db: AsyncSession,
    user: User,
    task: str,
    system: str,
    messages: list[Message],
    tools: list[ToolSpec] | None = None,
    executor: ToolExecutor | None = None,
    on_text: TextCallback = None,
    on_event: EventCallback = None,
    max_tokens: int = 8000,
    max_rounds: int = 6,
    json_mode: bool = False,
) -> LLMResult:
    ok, reason = await ai_available(db, user)
    if not ok:
        raise AIDisabledError(reason)
    await check_limit(db, user)
    s = (await get_user_settings(db, user.id))["ai"]
    chain = await provider_chain(db, user.id, s, task)
    if not chain:
        raise AIDisabledError("Kein KI-Provider für diese Aufgabe konfiguriert.")
    temperature = s.get("temperature")
    last_error: Exception | None = None

    for idx, cfg in enumerate(chain):
        provider = cfg.build()
        native = provider.to_native(messages)
        streamed = {"any": False}

        async def _on_text(t: str) -> None:
            streamed["any"] = True
            if on_text:
                await on_text(t)

        total_in = total_out = 0
        text_parts: list[str] = []
        calls_log: list[dict[str, Any]] = []
        started = time.monotonic()
        try:
            for _round in range(max_rounds):
                res = await provider.complete(
                    system=system, messages=native, model=cfg.model, tools=tools, temperature=temperature,
                    max_tokens=max_tokens, on_text=_on_text, json_mode=json_mode,
                )
                total_in += res.input_tokens
                total_out += res.output_tokens
                if res.text:
                    text_parts.append(res.text)
                if not res.tool_calls or not executor:
                    break
                results = []
                for call in res.tool_calls:
                    if on_event:
                        await on_event("tool", {"name": call.name, "status": "running"})
                    try:
                        out = await executor(call)
                    except Exception as e:  # noqa: BLE001 - Tool-Fehler gehen als Ergebnis an das Modell
                        log.exception("Tool %s fehlgeschlagen", call.name)
                        out = json.dumps({"error": str(e)})
                    calls_log.append({"name": call.name, "arguments": call.arguments})
                    results.append((call, out))
                    if on_event:
                        await on_event("tool", {"name": call.name, "status": "done"})
                native += provider.continuation(res, results)
            else:
                text_parts.append("\n(Maximale Anzahl an Tool-Aufrufen erreicht.)")
        except ProviderError as e:
            last_error = e
            await record_usage(db, user_id=user.id, task=task, provider=cfg.name, model=cfg.model,
                               input_tokens=total_in, output_tokens=total_out,
                               duration_ms=int((time.monotonic() - started) * 1000), success=False, error=str(e))
            log.warning("Provider %s fehlgeschlagen: %s", cfg.name, e)
            # Kein Fallback, wenn bereits Text an den Benutzer gestreamt wurde
            if streamed["any"] or idx == len(chain) - 1:
                raise
            if on_event:
                await on_event("fallback", {"from": cfg.name, "to": chain[idx + 1].name, "reason": str(e)[:200]})
            continue

        text = "\n\n".join(p for p in text_parts if p)
        content = {"system_chars": len(system), "messages": [m.content for m in messages][-4:], "response": text} \
            if s.get("log_content") else None
        await record_usage(db, user_id=user.id, task=task, provider=cfg.name, model=cfg.model, input_tokens=total_in,
                           output_tokens=total_out, duration_ms=int((time.monotonic() - started) * 1000), content=content)
        return LLMResult(text=text, provider=cfg.name, model=cfg.model, input_tokens=total_in, output_tokens=total_out,
                         tool_calls=calls_log, fallback_used=idx > 0)
    raise last_error or AIDisabledError("Kein KI-Provider verfügbar")


def parse_json(text: str) -> Any:
    """Robust JSON aus einer Modellantwort lesen (auch in ```json-Blöcken)."""
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    candidate = m.group(1) if m else text
    start = min((i for i in (candidate.find("{"), candidate.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError("Keine JSON-Antwort erhalten")
    end = max(candidate.rfind("}"), candidate.rfind("]"))
    return json.loads(candidate[start: end + 1])
