from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.core.access import get_owned, get_readable, get_writable, readable_clause
from app.core.deps import DB, CurrentUser, SubjectId
from app.models import (
    NUTRIENT_KEYS,
    DayTemplate,
    Favorite,
    Food,
    MealEntry,
    Recipe,
    RecipeIngredient,
    Role,
    WaterEntry,
)
from app.services.app_settings import get_user_settings
from app.services.meals import build_meal_entry, day_summary, recent_foods, recipe_nutrition
from app.services.off import lookup_barcode, search_off

router = APIRouter(tags=["nutrition"])


def food_out(f: Food, user_id: int) -> dict[str, Any]:
    return {**f.model_dump(exclude={"fetched_at"}), "own": f.owner_id == user_id}


# ================================================================ Lebensmittel
class FoodIn(BaseModel):
    name: str
    brand: str = ""
    barcode: str | None = None
    kcal: float = Field(0, ge=0)
    protein: float = Field(0, ge=0)
    carbs: float = Field(0, ge=0)
    fat: float = Field(0, ge=0)
    fiber: float = Field(0, ge=0)
    sugar: float = Field(0, ge=0)
    sat_fat: float = Field(0, ge=0)
    salt: float = Field(0, ge=0)
    micros: dict[str, float] = {}
    serving_g: float | None = None
    serving_label: str = ""
    source: str = "custom"


@router.get("/foods/search")
async def search_foods(user: CurrentUser, db: DB, q: str = Query(min_length=2), online: bool = True) -> dict[str, Any]:
    local = (
        await db.exec(
            select(Food).where(readable_clause(Food, "food", user.id), col(Food.name).ilike(f"%{q}%"))
            .order_by(col(Food.owner_id).is_(None), Food.name).limit(30)
        )
    ).all()
    results = [food_out(f, user.id) for f in local]
    if online and len(local) < 10:
        seen = {f.id for f in local}
        results += [food_out(f, user.id) for f in await search_off(db, q) if f.id not in seen]
    return {"results": results}


@router.get("/foods/barcode/{code}")
async def barcode(code: str, user: CurrentUser, db: DB) -> dict[str, Any]:
    own = (await db.exec(select(Food).where(Food.barcode == code, Food.owner_id == user.id))).first()
    food = own or await lookup_barcode(db, code)
    if not food:
        raise HTTPException(404, "Produkt nicht gefunden – du kannst es als eigenes Lebensmittel anlegen")
    return food_out(food, user.id)


@router.get("/foods/recent")
async def foods_recent(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    out = []
    for fid in await recent_foods(db, user.id):
        f = await db.get(Food, fid)
        if f:
            out.append(food_out(f, user.id))
    return out


@router.get("/foods/mine")
async def my_foods(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(Food).where(Food.owner_id == user.id).order_by(Food.name))).all()
    return [food_out(f, user.id) for f in rows]


@router.get("/foods/{fid}")
async def get_food(fid: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    return food_out(await get_readable(db, Food, "food", fid, user), user.id)


@router.post("/foods")
async def create_food(body: FoodIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    f = Food(**body.model_dump(), owner_id=user.id, visibility="private")
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return food_out(f, user.id)


@router.patch("/foods/{fid}")
async def update_food(fid: int, body: dict[str, Any], user: CurrentUser, db: DB) -> dict[str, Any]:
    f = await get_writable(db, Food, "food", fid, user)
    for k in FoodIn.model_fields:
        if k in body:
            setattr(f, k, body[k])
    db.add(f)
    await db.commit()
    return food_out(f, user.id)


@router.delete("/foods/{fid}")
async def delete_food(fid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    f = await get_writable(db, Food, "food", fid, user)
    if f.owner_id is None and user.role != Role.admin:
        raise HTTPException(403, "Globale Lebensmittel können nicht gelöscht werden")
    await db.delete(f)
    await db.commit()
    return {"ok": True}


# ================================================================ Rezepte
class IngredientIn(BaseModel):
    food_id: int
    grams: float = Field(gt=0)


class RecipeIn(BaseModel):
    name: str
    servings: float = Field(1, gt=0)
    instructions: str = ""
    tags: list[str] = []
    ingredients: list[IngredientIn] = []


async def _recipe_out(db: DB, r: Recipe, user_id: int) -> dict[str, Any]:
    return {**r.model_dump(), "own": r.owner_id == user_id, **await recipe_nutrition(db, r)}


@router.get("/recipes")
async def list_recipes(user: CurrentUser, db: DB, q: str | None = None) -> list[dict[str, Any]]:
    stmt = select(Recipe).where(readable_clause(Recipe, "recipe", user.id)).order_by(Recipe.name)
    if q:
        stmt = stmt.where(col(Recipe.name).ilike(f"%{q}%"))
    return [await _recipe_out(db, r, user.id) for r in (await db.exec(stmt)).all()]


@router.get("/recipes/{rid}")
async def get_recipe(rid: int, user: CurrentUser, db: DB) -> dict[str, Any]:
    return await _recipe_out(db, await get_readable(db, Recipe, "recipe", rid, user), user.id)


async def _write_ingredients(db: DB, r: Recipe, items: list[IngredientIn], user: CurrentUser) -> None:
    for old in (await db.exec(select(RecipeIngredient).where(RecipeIngredient.recipe_id == r.id))).all():
        await db.delete(old)
    for i, it in enumerate(items):
        await get_readable(db, Food, "food", it.food_id, user)
        db.add(RecipeIngredient(recipe_id=r.id, food_id=it.food_id, grams=it.grams, position=i))


@router.post("/recipes")
async def create_recipe(body: RecipeIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    r = Recipe(owner_id=user.id, **body.model_dump(exclude={"ingredients"}))
    db.add(r)
    await db.flush()
    await _write_ingredients(db, r, body.ingredients, user)
    await db.commit()
    return await _recipe_out(db, r, user.id)


@router.put("/recipes/{rid}")
async def update_recipe(rid: int, body: RecipeIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    r = await get_writable(db, Recipe, "recipe", rid, user)
    for k, v in body.model_dump(exclude={"ingredients"}).items():
        setattr(r, k, v)
    db.add(r)
    await _write_ingredients(db, r, body.ingredients, user)
    await db.commit()
    return await _recipe_out(db, r, user.id)


@router.delete("/recipes/{rid}")
async def delete_recipe(rid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    r = await get_writable(db, Recipe, "recipe", rid, user)
    await db.delete(r)
    await db.commit()
    return {"ok": True}


# ================================================================ Mahlzeiten-Log
class MealIn(BaseModel):
    day: date | None = None
    slot: str = "Snacks"
    food_id: int | None = None
    recipe_id: int | None = None
    grams: float | None = None
    servings: float | None = None
    name: str | None = None
    kcal: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None
    fiber: float | None = None
    sugar: float | None = None
    sat_fat: float | None = None
    salt: float | None = None
    source: str = "manual"
    client_id: str | None = None


@router.get("/meals")
async def get_day(subject: SubjectId, db: DB, day: date | None = None) -> dict[str, Any]:
    s = await get_user_settings(db, subject)
    return await day_summary(db, subject, day or date.today(), s["meal_slots"])


@router.post("/meals")
async def add_meal(body: MealIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    if body.client_id:
        ex = (await db.exec(select(MealEntry).where(MealEntry.user_id == user.id, MealEntry.client_id == body.client_id))).first()
        if ex:
            return ex.model_dump()
    e = await build_meal_entry(db, user, body.model_dump())
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return e.model_dump()


@router.post("/meals/batch")
async def add_meals(items: list[MealIn], user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    return [await add_meal(it, user, db) for it in items]


class MealPatch(BaseModel):
    slot: str | None = None
    grams: float | None = None
    servings: float | None = None
    day: date | None = None


@router.patch("/meals/{mid}")
async def patch_meal(mid: int, body: MealPatch, user: CurrentUser, db: DB) -> dict[str, Any]:
    e = await get_owned(db, MealEntry, mid, user.id)
    if body.slot:
        e.slot = body.slot
    if body.day:
        e.day = body.day
    if (body.grams and e.grams) or (body.servings and e.servings):
        factor = (body.grams / e.grams) if body.grams and e.grams else (body.servings / e.servings)
        for k in NUTRIENT_KEYS:
            setattr(e, k, round(getattr(e, k) * factor, 2))
        e.micros = {k: round(v * factor, 3) for k, v in (e.micros or {}).items()}
        e.grams = round(e.grams * factor, 1)
        if e.servings:
            e.servings = round(e.servings * factor, 2)
    db.add(e)
    await db.commit()
    return e.model_dump()


@router.delete("/meals/{mid}")
async def delete_meal(mid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    e = await get_owned(db, MealEntry, mid, user.id)
    await db.delete(e)
    await db.commit()
    return {"ok": True}


class CopyIn(BaseModel):
    from_day: date | None = None
    to_day: date | None = None
    slot: str | None = None


@router.post("/meals/copy")
async def copy_day(body: CopyIn, user: CurrentUser, db: DB) -> dict[str, int]:
    """„Gestern kopieren": kopiert alle (oder einen Slot) Einträge eines Tages."""
    to_day = body.to_day or date.today()
    from_day = body.from_day or (to_day - timedelta(days=1))
    stmt = select(MealEntry).where(MealEntry.user_id == user.id, MealEntry.day == from_day)
    if body.slot:
        stmt = stmt.where(MealEntry.slot == body.slot)
    n = 0
    for e in (await db.exec(stmt)).all():
        data = e.model_dump(exclude={"id", "created_at", "client_id"})
        db.add(MealEntry(**{**data, "day": to_day, "source": "copy"}))
        n += 1
    await db.commit()
    return {"copied": n}


# ================================================================ Favoriten
class FavIn(BaseModel):
    food_id: int | None = None
    recipe_id: int | None = None
    default_grams: float = 100


@router.get("/favorites")
async def list_favorites(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    out = []
    for fav in (await db.exec(select(Favorite).where(Favorite.user_id == user.id))).all():
        item: dict[str, Any] = fav.model_dump()
        if fav.food_id and (f := await db.get(Food, fav.food_id)):
            item["food"] = food_out(f, user.id)
        if fav.recipe_id and (r := await db.get(Recipe, fav.recipe_id)):
            item["recipe"] = {"id": r.id, "name": r.name}
        out.append(item)
    return out


@router.post("/favorites")
async def add_favorite(body: FavIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    if body.food_id:
        await get_readable(db, Food, "food", body.food_id, user)
    elif body.recipe_id:
        await get_readable(db, Recipe, "recipe", body.recipe_id, user)
    else:
        raise HTTPException(422, "food_id oder recipe_id angeben")
    existing = (
        await db.exec(select(Favorite).where(Favorite.user_id == user.id, Favorite.food_id == body.food_id,
                                             Favorite.recipe_id == body.recipe_id))
    ).first()
    if existing:
        return existing.model_dump()
    f = Favorite(user_id=user.id, **body.model_dump())
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return f.model_dump()


@router.delete("/favorites/{fid}")
async def delete_favorite(fid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    f = await get_owned(db, Favorite, fid, user.id)
    await db.delete(f)
    await db.commit()
    return {"ok": True}


# ================================================================ Vorlagen-Tage
class TemplateIn(BaseModel):
    name: str
    from_day: date


@router.get("/day-templates")
async def list_templates(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.exec(select(DayTemplate).where(DayTemplate.user_id == user.id).order_by(DayTemplate.name))).all()
    return [{**r.model_dump(), "kcal": round(sum(e.get("kcal", 0) for e in r.entries))} for r in rows]


@router.post("/day-templates")
async def create_template(body: TemplateIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    entries = (await db.exec(select(MealEntry).where(MealEntry.user_id == user.id, MealEntry.day == body.from_day))).all()
    if not entries:
        raise HTTPException(422, "An diesem Tag gibt es keine Einträge")
    t = DayTemplate(user_id=user.id, name=body.name,
                    entries=[e.model_dump(exclude={"id", "created_at", "day", "user_id", "client_id"}) for e in entries])
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t.model_dump()


@router.post("/day-templates/{tid}/apply")
async def apply_template(tid: int, user: CurrentUser, db: DB, day: date | None = None) -> dict[str, int]:
    t = await get_owned(db, DayTemplate, tid, user.id)
    for e in t.entries:
        db.add(MealEntry(**{**e, "user_id": user.id, "day": day or date.today(), "source": "template"}))
    await db.commit()
    return {"added": len(t.entries)}


@router.delete("/day-templates/{tid}")
async def delete_template(tid: int, user: CurrentUser, db: DB) -> dict[str, bool]:
    t = await get_owned(db, DayTemplate, tid, user.id)
    await db.delete(t)
    await db.commit()
    return {"ok": True}


# ================================================================ Wasser
class WaterIn(BaseModel):
    day: date | None = None
    ml: int = Field(250, ge=-2000, le=3000)
    client_id: str | None = None


@router.post("/water")
async def add_water(body: WaterIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    day = body.day or date.today()
    if body.client_id:
        ex = (await db.exec(select(WaterEntry).where(WaterEntry.user_id == user.id, WaterEntry.client_id == body.client_id))).first()
        if ex:
            return ex.model_dump()
    w = WaterEntry(user_id=user.id, day=day, ml=body.ml, client_id=body.client_id)
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return w.model_dump()


@router.delete("/water/last")
async def undo_water(user: CurrentUser, db: DB, day: date | None = None) -> dict[str, bool]:
    w = (
        await db.exec(select(WaterEntry).where(WaterEntry.user_id == user.id, WaterEntry.day == (day or date.today()))
                      .order_by(WaterEntry.created_at.desc()).limit(1))
    ).first()
    if w:
        await db.delete(w)
        await db.commit()
    return {"ok": True}
