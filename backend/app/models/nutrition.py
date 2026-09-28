from datetime import date, datetime
from typing import Any

from sqlmodel import Field, SQLModel

from app.models.base import json_field, text_field, ts_field, user_fk

NUTRIENT_KEYS = ("kcal", "protein", "carbs", "fat", "fiber", "sugar", "sat_fat", "salt")


class Food(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int | None = Field(default=None, foreign_key="user.id", index=True, ondelete="CASCADE")
    barcode: str | None = Field(default=None, index=True)
    name: str = Field(index=True)
    brand: str = ""
    source: str = "custom"  # off|custom|label|seed
    # Nährwerte pro 100 g
    kcal: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    fiber: float = 0
    sugar: float = 0
    sat_fat: float = 0
    salt: float = 0
    micros: dict[str, float] = json_field()  # z. B. {"vitamin_c_mg": 12}
    serving_g: float | None = None
    serving_label: str = ""
    visibility: str = "private"
    fetched_at: datetime | None = ts_field(default_now=False)
    created_at: datetime = ts_field()


class Recipe(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int | None = Field(default=None, foreign_key="user.id", index=True, ondelete="CASCADE")
    name: str
    servings: float = 1
    instructions: str = text_field()
    tags: list[str] = json_field(list)
    visibility: str = "private"
    created_at: datetime = ts_field()


class RecipeIngredient(SQLModel, table=True):
    __tablename__ = "recipe_ingredient"
    id: int | None = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True, ondelete="CASCADE")
    food_id: int = Field(foreign_key="food.id", ondelete="CASCADE")
    grams: float = 100
    position: int = 0


class MealEntry(SQLModel, table=True):
    __tablename__ = "meal_entry"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    client_id: str | None = Field(default=None, index=True, max_length=64)
    day: date = Field(index=True)
    slot: str = "Frühstück"
    food_id: int | None = Field(default=None, foreign_key="food.id", ondelete="SET NULL")
    recipe_id: int | None = Field(default=None, foreign_key="recipe.id", ondelete="SET NULL")
    name: str = ""
    grams: float = 100
    servings: float | None = None
    # Snapshot der Nährwerte (absolut für diese Portion)
    kcal: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    fiber: float = 0
    sugar: float = 0
    sat_fat: float = 0
    salt: float = 0
    micros: dict[str, float] = json_field()
    source: str = "manual"  # manual|barcode|photo|coach|copy|template
    created_at: datetime = ts_field()


class Favorite(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    food_id: int | None = Field(default=None, foreign_key="food.id", ondelete="CASCADE")
    recipe_id: int | None = Field(default=None, foreign_key="recipe.id", ondelete="CASCADE")
    default_grams: float = 100
    created_at: datetime = ts_field()


class DayTemplate(SQLModel, table=True):
    __tablename__ = "day_template"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    name: str
    entries: list[dict[str, Any]] = json_field(list)
    created_at: datetime = ts_field()


class WaterEntry(SQLModel, table=True):
    __tablename__ = "water_entry"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    client_id: str | None = Field(default=None, index=True, max_length=64)
    day: date = Field(index=True)
    ml: int = 250
    created_at: datetime = ts_field()


class BodyMeasurement(SQLModel, table=True):
    __tablename__ = "body_measurement"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    client_id: str | None = Field(default=None, index=True, max_length=64)
    day: date = Field(index=True)
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    waist_cm: float | None = None
    chest_cm: float | None = None
    hips_cm: float | None = None
    arm_cm: float | None = None
    thigh_cm: float | None = None
    neck_cm: float | None = None
    notes: str = text_field()
    source: str = "manual"
    created_at: datetime = ts_field()


class ProgressPhoto(SQLModel, table=True):
    __tablename__ = "progress_photo"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    day: date = Field(index=True)
    filename: str
    pose: str = "front"  # front|side|back
    note: str = ""
    created_at: datetime = ts_field()


class MetricDefinition(SQLModel, table=True):
    __tablename__ = "metric_definition"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    name: str
    kind: str = "number"  # number|scale|bool|text
    unit: str = ""
    scale_min: float | None = 1
    scale_max: float | None = 10
    target: float | None = None
    chart: str = "line"  # line|bar
    color: str | None = None
    position: int = 0
    archived: bool = False


class MetricEntry(SQLModel, table=True):
    __tablename__ = "metric_entry"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    metric_id: int = Field(foreign_key="metric_definition.id", index=True, ondelete="CASCADE")
    day: date = Field(index=True)
    value_num: float | None = None
    value_text: str | None = None
    created_at: datetime = ts_field()


class Dashboard(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    name: str = "Heute"
    position: int = 0
    # [{"id":"w1","type":"macros","w":2,"h":2,"visible":true,"config":{}}]
    widgets: list[dict[str, Any]] = json_field(list)
