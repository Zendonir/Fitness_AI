from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.access import get_readable
from app.models import NUTRIENT_KEYS, Food, MealEntry, Recipe, RecipeIngredient, User, WaterEntry
from app.services.nutrition import scale_nutrients
from app.services.targets import user_targets


def _zero() -> dict[str, float]:
    return {k: 0.0 for k in NUTRIENT_KEYS}


async def recipe_nutrition(db: AsyncSession, recipe: Recipe) -> dict[str, Any]:
    ings = (
        await db.exec(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id).order_by(RecipeIngredient.position))
    ).all()
    total = _zero()
    micros: dict[str, float] = {}
    grams = 0.0
    items = []
    for ing in ings:
        food = await db.get(Food, ing.food_id)
        if not food:
            continue
        n = scale_nutrients(food, ing.grams)
        for k in NUTRIENT_KEYS:
            total[k] += n[k]
        for mk, mv in n["micros"].items():
            micros[mk] = micros.get(mk, 0) + mv
        grams += ing.grams
        items.append({"id": ing.id, "food_id": food.id, "name": food.name, "brand": food.brand, "grams": ing.grams,
                      "kcal": n["kcal"], "protein": n["protein"]})
    servings = recipe.servings or 1
    per = {k: round(v / servings, 1) for k, v in total.items()}
    return {
        "ingredients": items,
        "total": {k: round(v, 1) for k, v in total.items()},
        "per_serving": per,
        "micros_total": {k: round(v, 2) for k, v in micros.items()},
        "total_grams": round(grams, 1),
        "serving_grams": round(grams / servings, 1) if servings else grams,
    }


async def build_meal_entry(db: AsyncSession, user: User, data: dict[str, Any]) -> MealEntry:
    """data: day, slot, food_id+grams | recipe_id+servings | name+Nährwerte (manuell)."""
    entry = MealEntry(user_id=user.id, day=data.get("day") or date.today(), slot=data.get("slot") or "Snacks",
                      source=data.get("source") or "manual", client_id=data.get("client_id"))
    if data.get("food_id"):
        food = await get_readable(db, Food, "food", int(data["food_id"]), user)
        grams = float(data.get("grams") or food.serving_g or 100)
        n = scale_nutrients(food, grams)
        entry.food_id, entry.grams = food.id, grams
        entry.name = f"{food.name}" + (f" ({food.brand})" if food.brand else "")
        for k in NUTRIENT_KEYS:
            setattr(entry, k, n[k])
        entry.micros = n["micros"]
    elif data.get("recipe_id"):
        recipe = await get_readable(db, Recipe, "recipe", int(data["recipe_id"]), user)
        nut = await recipe_nutrition(db, recipe)
        servings = float(data.get("servings") or 1)
        entry.recipe_id, entry.servings, entry.name = recipe.id, servings, recipe.name
        entry.grams = round(nut["serving_grams"] * servings, 1)
        for k in NUTRIENT_KEYS:
            setattr(entry, k, round(nut["per_serving"][k] * servings, 1))
        rs = recipe.servings or 1
        entry.micros = {k: round(v / rs * servings, 2) for k, v in nut["micros_total"].items()}
    else:
        if not data.get("name"):
            raise HTTPException(422, "Lebensmittel, Rezept oder Name mit Nährwerten angeben")
        entry.name = str(data["name"])[:200]
        entry.grams = float(data.get("grams") or 0)
        for k in NUTRIENT_KEYS:
            setattr(entry, k, max(0.0, float(data.get(k) or 0)))
    return entry


async def day_summary(db: AsyncSession, user_id: int, day: date, slots: list[str]) -> dict[str, Any]:
    entries = (
        await db.exec(select(MealEntry).where(MealEntry.user_id == user_id, MealEntry.day == day).order_by(MealEntry.created_at))
    ).all()
    totals = _zero()
    micros: dict[str, float] = {}
    by_slot: dict[str, list[dict[str, Any]]] = {s: [] for s in slots}
    for e in entries:
        for k in NUTRIENT_KEYS:
            totals[k] += getattr(e, k)
        for mk, mv in (e.micros or {}).items():
            micros[mk] = micros.get(mk, 0) + mv
        by_slot.setdefault(e.slot, []).append(e.model_dump())
    water = (
        await db.exec(select(func.coalesce(func.sum(WaterEntry.ml), 0)).where(WaterEntry.user_id == user_id, WaterEntry.day == day))
    ).one()
    targets = await user_targets(db, user_id, day)
    return {
        "day": day,
        "slots": [{"name": s, "entries": by_slot[s], "kcal": round(sum(x["kcal"] for x in by_slot[s]), 1)} for s in by_slot],
        "totals": {k: round(v, 1) for k, v in totals.items()},
        "micros": {k: round(v, 2) for k, v in micros.items()},
        "water_ml": int(water or 0),
        "targets": targets["today"],
        "day_type": targets["day_type"],
        "floors": targets["floors"],
    }


async def recent_foods(db: AsyncSession, user_id: int, limit: int = 15) -> list[int]:
    rows = (
        await db.exec(
            select(MealEntry.food_id, func.max(MealEntry.created_at))
            .where(MealEntry.user_id == user_id, col(MealEntry.food_id).is_not(None))
            .group_by(MealEntry.food_id).order_by(func.max(MealEntry.created_at).desc()).limit(limit)
        )
    ).all()
    return [r[0] for r in rows]
