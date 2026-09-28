"""Open Food Facts – Suche und Barcode-Lookup mit lokalem Cache (Tabelle `food`, owner_id NULL)."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models import Food

log = logging.getLogger(__name__)

FIELDS = "code,product_name,product_name_de,generic_name,brands,nutriments,serving_size,serving_quantity"
CACHE_DAYS = 30

# OFF-Schlüssel -> (Name in micros, Faktor von g auf Zieleinheit)
MICROS = {
    "vitamin-c_100g": ("vitamin_c_mg", 1000),
    "vitamin-d_100g": ("vitamin_d_ug", 1_000_000),
    "vitamin-b12_100g": ("vitamin_b12_ug", 1_000_000),
    "calcium_100g": ("calcium_mg", 1000),
    "iron_100g": ("iron_mg", 1000),
    "magnesium_100g": ("magnesium_mg", 1000),
    "potassium_100g": ("potassium_mg", 1000),
    "zinc_100g": ("zinc_mg", 1000),
    "sodium_100g": ("sodium_mg", 1000),
}


def _f(n: dict[str, Any], key: str) -> float:
    v = n.get(key)
    try:
        return round(float(v), 2) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def product_to_food(p: dict[str, Any]) -> dict[str, Any] | None:
    n = p.get("nutriments") or {}
    name = p.get("product_name_de") or p.get("product_name") or p.get("generic_name")
    if not name:
        return None
    kcal = _f(n, "energy-kcal_100g") or round(_f(n, "energy_100g") / 4.184, 1)
    micros = {}
    for key, (mk, factor) in MICROS.items():
        if n.get(key) not in (None, ""):
            micros[mk] = round(_f(n, key) * factor, 2)
    serving = p.get("serving_quantity")
    try:
        serving = float(serving) if serving else None
    except (TypeError, ValueError):
        serving = None
    return {
        "barcode": p.get("code"),
        "name": name.strip()[:200],
        "brand": (p.get("brands") or "").split(",")[0].strip()[:120],
        "source": "off",
        "kcal": kcal,
        "protein": _f(n, "proteins_100g"),
        "carbs": _f(n, "carbohydrates_100g"),
        "fat": _f(n, "fat_100g"),
        "fiber": _f(n, "fiber_100g"),
        "sugar": _f(n, "sugars_100g"),
        "sat_fat": _f(n, "saturated-fat_100g"),
        "salt": _f(n, "salt_100g"),
        "micros": micros,
        "serving_g": serving,
        "serving_label": (p.get("serving_size") or "")[:60],
        "visibility": "public",
    }


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=8, headers={"User-Agent": settings.off_user_agent})


async def _upsert(db: AsyncSession, data: dict[str, Any]) -> Food:
    existing = None
    if data.get("barcode"):
        existing = (
            await db.exec(select(Food).where(Food.barcode == data["barcode"], Food.owner_id.is_(None)))
        ).first()
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        existing.fetched_at = datetime.now(UTC)
        food = existing
    else:
        food = Food(**data, fetched_at=datetime.now(UTC))
    db.add(food)
    await db.commit()
    await db.refresh(food)
    return food


async def lookup_barcode(db: AsyncSession, code: str) -> Food | None:
    code = "".join(ch for ch in code if ch.isdigit())
    cached = (await db.exec(select(Food).where(Food.barcode == code, Food.owner_id.is_(None)))).first()
    if cached and cached.fetched_at:
        fetched = cached.fetched_at if cached.fetched_at.tzinfo else cached.fetched_at.replace(tzinfo=UTC)
        if fetched > datetime.now(UTC) - timedelta(days=CACHE_DAYS):
            return cached
    try:
        async with _client() as c:
            r = await c.get(f"{settings.open_food_facts_url}/api/v2/product/{code}", params={"fields": FIELDS})
        if r.status_code == 200 and r.json().get("status") == 1:
            data = product_to_food(r.json()["product"])
            if data:
                data["barcode"] = code
                return await _upsert(db, data)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("OFF-Barcode-Lookup fehlgeschlagen: %s", e)
    return cached


async def search_off(db: AsyncSession, query: str, limit: int = 20) -> list[Food]:
    try:
        async with _client() as c:
            r = await c.get(
                f"{settings.open_food_facts_url}/cgi/search.pl",
                params={"search_terms": query, "search_simple": 1, "action": "process", "json": 1,
                        "page_size": limit, "fields": FIELDS, "lc": "de", "cc": "de"},
            )
        r.raise_for_status()
        products = r.json().get("products", [])
    except (httpx.HTTPError, ValueError) as e:
        log.warning("OFF-Suche fehlgeschlagen: %s", e)
        return []
    out = []
    for p in products:
        data = product_to_food(p)
        if data and data["kcal"] > 0:
            out.append(await _upsert(db, data))
    return out
