"""Provider-Registry, Schlüsselauflösung, Modellwahl pro Aufgabe und Preise."""

from dataclasses import dataclass
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.base import Provider
from app.ai.providers.openai_provider import OllamaProvider, OpenAIProvider
from app.core.config import settings
from app.core.security import decrypt
from app.models import UserAIKey
from app.services.app_settings import get_app_setting

PROVIDERS: dict[str, type[Provider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}

TASKS = {
    "chat": "Chat",
    "vision": "Foto-Erkennung",
    "weekly_report": "Wochen-/Monatsbericht",
    "summary": "Tägliche Zusammenfassung",
    "briefing": "Briefing & Check-in",
    "meal_plan": "Mahlzeitenplanung",
    "plan_review": "Plananpassung",
}

# USD pro 1 Mio. Tokens (Eingabe, Ausgabe). Präfix-Match, längster gewinnt.
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4": (1.0, 5.0),
    "claude": (5.0, 25.0),
    "gpt-5-nano": (0.05, 0.4),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5": (1.25, 10.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gpt-4o": (2.5, 10.0),
    "o4-mini": (1.1, 4.4),
    "o3": (2.0, 8.0),
    "gpt": (2.5, 10.0),
}


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int,
                  overrides: dict[str, Any] | None = None) -> float:
    if provider == "ollama":
        return 0.0
    table = {**DEFAULT_PRICING, **{k: tuple(v) for k, v in (overrides or {}).items()}}
    match = max((k for k in table if model.startswith(k)), key=len, default=None)
    pin, pout = table[match] if match else ((5.0, 25.0) if provider == "anthropic" else (2.5, 10.0))
    return round(input_tokens / 1e6 * pin + output_tokens / 1e6 * pout, 6)


@dataclass
class ProviderConfig:
    name: str
    model: str
    api_key: str | None
    base_url: str | None
    source: str  # user|global|env

    def build(self) -> Provider:
        return PROVIDERS[self.name](api_key=self.api_key, base_url=self.base_url)


async def resolve_credentials(db: AsyncSession, user_id: int | None, provider: str) -> tuple[str | None, str | None, str]:
    """Reihenfolge: eigener Key des Benutzers > Admin-Panel > ENV."""
    if user_id and provider in ("anthropic", "openai"):
        row = (await db.exec(select(UserAIKey).where(UserAIKey.user_id == user_id, UserAIKey.provider == provider))).first()
        if row and (k := decrypt(row.key_enc)):
            return k, None, "user"
    keys = await get_app_setting(db, "ai_keys", {})
    if provider == "ollama":
        url = keys.get("ollama_base_url") or settings.ollama_base_url
        return None, url or None, "global" if keys.get("ollama_base_url") else "env"
    k = decrypt(keys.get(provider))
    if k:
        return k, None, "global"
    env = settings.anthropic_api_key if provider == "anthropic" else settings.openai_api_key
    return env or None, None, "env"


def is_configured(provider: str, key: str | None, url: str | None) -> bool:
    return bool(url) if provider == "ollama" else bool(key)


async def default_model(db: AsyncSession, provider: str) -> str:
    models = await get_app_setting(db, "default_models", {})
    if models.get(provider):
        return models[provider]
    return {"anthropic": settings.default_anthropic_model, "openai": settings.default_openai_model,
            "ollama": settings.default_ollama_model}[provider]


async def provider_chain(db: AsyncSession, user_id: int | None, ai_settings: dict[str, Any], task: str) -> list[ProviderConfig]:
    """Primärer Provider für die Aufgabe + Fallbacks (alle anderen konfigurierten)."""
    route = (ai_settings.get("task_routing") or {}).get(task) or {}
    system_default = await get_app_setting(db, "default_provider", settings.default_ai_provider)
    primary = route.get("provider") or ai_settings.get("provider") or system_default
    if primary not in PROVIDERS:
        primary = "anthropic"
    model = route.get("model") or (ai_settings.get("model") if (ai_settings.get("provider") or system_default) == primary else None)
    order = [primary] + [p for p in ("anthropic", "openai", "ollama") if p != primary]
    chain = []
    for name in order:
        key, url, source = await resolve_credentials(db, user_id, name)
        if not is_configured(name, key, url):
            continue
        m = model if name == primary and model else await default_model(db, name)
        chain.append(ProviderConfig(name, m, key, url, source))
    if not ai_settings.get("fallback", True):
        chain = [c for c in chain if c.name == primary]
    return chain
