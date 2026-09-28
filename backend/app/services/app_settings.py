"""Globale App-Einstellungen (Admin) und Benutzereinstellungen mit Standardwerten."""

import copy
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models import AppSetting, UserSettings

DEFAULT_USER_SETTINGS: dict[str, Any] = {
    "language": "de",
    "units": {"weight": "kg", "distance": "km", "energy": "kcal"},
    "theme": {
        "mode": "system",  # light|dark|system
        "accent": "#22c55e",
        "density": "comfortable",  # compact|comfortable|large
        "macro_colors": {"protein": "#3b82f6", "carbs": "#f59e0b", "fat": "#ef4444", "fiber": "#10b981"},
        "muscle_colors": {},
    },
    "meal_slots": ["Frühstück", "Mittagessen", "Abendessen", "Snacks"],
    "visible_nutrients": ["kcal", "protein", "carbs", "fat", "fiber", "water"],
    "water_goal_ml": 2500,
    "rest_timer_default": 120,
    "rest_timer_vibrate": True,
    "rest_timer_push": True,
    "ai": {
        "enabled": True,
        "provider": "",  # leer = globaler Standard
        "model": "",
        "temperature": 0.7,
        "style_length": "short",  # short|detailed
        "style_tone": "motivating",  # motivating|factual
        "task_routing": {},  # {"chat": {"provider":"anthropic","model":"…"}, "vision": {...}, "weekly_report": {...}}
        "fallback": True,
        "log_content": False,
        "consents": {"body": False, "photos": False, "metrics": False, "nutrition": True, "training": True},
        "proactive": {
            "enabled": True,
            "plateau": True,
            "protein_low": True,
            "missed_training": True,
            "new_pr": True,
            "deload": True,
            "plan_suggestions": True,
        },
        "briefing": {"morning_enabled": False, "morning_time": "07:00", "evening_enabled": False, "evening_time": "20:30"},
        "push": {"hints": True, "briefings": True, "timer": True},
    },
}


def deep_merge(base: dict, override: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


async def get_app_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = await db.get(AppSetting, key)
    return default if row is None or row.value is None else row.value


async def set_app_setting(db: AsyncSession, key: str, value: Any) -> None:
    row = await db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
    else:
        row.value = value
    db.add(row)
    await db.commit()


async def system_flags(db: AsyncSession) -> dict[str, Any]:
    return {
        "open_registration": bool(await get_app_setting(db, "open_registration", False)),
        "ai_enabled": bool(await get_app_setting(db, "ai_enabled", settings.ai_enabled)),
        "default_monthly_limit_usd": float(
            await get_app_setting(db, "default_monthly_limit_usd", settings.ai_default_monthly_limit_usd)
        ),
        "default_provider": await get_app_setting(db, "default_provider", settings.default_ai_provider),
    }


async def get_user_settings(db: AsyncSession, user_id: int) -> dict[str, Any]:
    admin_defaults = await get_app_setting(db, "user_defaults", {})
    row = await db.get(UserSettings, user_id)
    return deep_merge(deep_merge(DEFAULT_USER_SETTINGS, admin_defaults), row.data if row else {})


async def update_user_settings(db: AsyncSession, user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    row = await db.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id, data={})
    row.data = deep_merge(row.data or {}, patch)
    db.add(row)
    await db.commit()
    return await get_user_settings(db, user_id)
