"""Makro-Rechner (Mifflin-St-Jeor) mit harten Untergrenzen.

Diese Funktionen sind die einzige Quelle für Tagesziele – auch KI-Vorschläge laufen
über `validate_targets`, damit keine Crash-Diäten entstehen können.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}
GOAL_ADJUST = {"bulk": 0.10, "maintain": 0.0, "cut": -0.15}
MAX_DEFICIT = 0.20  # max. 20 % unter dem Bedarf
KCAL_MIN = {"male": 1500, "female": 1200}
PROTEIN_PER_KG = {"bulk": 1.8, "maintain": 1.8, "cut": 2.0}
PROTEIN_MIN_PER_KG = 1.2
PROTEIN_MIN_ABS = 60.0
FAT_MIN_PER_KG = 0.6
TRAINING_DAY_SHIFT = 0.08  # Anteil, um den Trainingstage höher liegen


@dataclass
class BodyData:
    sex: str = "male"
    age: int = 30
    height_cm: float = 175
    weight_kg: float = 75
    activity_level: str = "moderate"
    goal: str = "maintain"
    training_days_per_week: int = 3


def age_from(birth: date | None, today: date | None = None) -> int:
    if not birth:
        return 30
    today = today or date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def bmr_mifflin(b: BodyData) -> float:
    base = 10 * b.weight_kg + 6.25 * b.height_cm - 5 * b.age
    return base + (5 if b.sex == "male" else -161)


def floors(b: BodyData) -> dict[str, float]:
    bmr = bmr_mifflin(b)
    tdee = bmr * ACTIVITY_FACTORS.get(b.activity_level, 1.55)
    kcal_floor = max(KCAL_MIN.get(b.sex, 1200), round(bmr), round(tdee * (1 - MAX_DEFICIT)))
    protein_floor = max(PROTEIN_MIN_ABS, round(b.weight_kg * PROTEIN_MIN_PER_KG))
    return {"kcal": float(kcal_floor), "protein": float(protein_floor), "fat": round(b.weight_kg * FAT_MIN_PER_KG)}


def _macros(kcal: float, b: BodyData, protein_override: float | None = None) -> dict[str, float]:
    protein = protein_override or round(b.weight_kg * PROTEIN_PER_KG.get(b.goal, 1.8))
    fat = max(round(b.weight_kg * 0.8), round(kcal * 0.25 / 9))
    carbs = max(0.0, round((kcal - protein * 4 - fat * 9) / 4))
    return {
        "kcal": round(kcal),
        "protein": float(protein),
        "carbs": float(carbs),
        "fat": float(fat),
        "fiber": float(round(kcal / 1000 * 14)),
        "water_ml": float(round(b.weight_kg * 35 / 50) * 50),
    }


def compute_targets(b: BodyData, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    bmr = bmr_mifflin(b)
    tdee = bmr * ACTIVITY_FACTORS.get(b.activity_level, 1.55)
    goal_kcal = tdee * (1 + GOAL_ADJUST.get(b.goal, 0.0))
    fl = floors(b)
    avg = max(goal_kcal, fl["kcal"])
    n = min(max(b.training_days_per_week, 0), 7)
    delta = TRAINING_DAY_SHIFT * avg
    training = avg + delta * (7 - n) / 7
    rest = max(avg - delta * n / 7, fl["kcal"])

    custom = custom or {}
    result = {
        "bmr": round(bmr),
        "tdee": round(tdee),
        "goal": b.goal,
        "floors": fl,
        "training": _macros(training, b),
        "rest": _macros(rest, b),
    }
    for day_type in ("training", "rest"):
        over = custom.get(day_type) or {}
        if over:
            result[day_type] = validate_targets({**result[day_type], **over}, b)
    return result


def validate_targets(t: dict[str, Any], b: BodyData) -> dict[str, float]:
    """Klemmt Ziele auf die Untergrenzen und rechnet Kohlenhydrate neu, falls nötig."""
    fl = floors(b)
    out = {k: float(v) for k, v in t.items() if isinstance(v, int | float)}
    out["kcal"] = max(out.get("kcal", fl["kcal"]), fl["kcal"])
    out["protein"] = max(out.get("protein", fl["protein"]), fl["protein"])
    out["fat"] = max(out.get("fat", fl["fat"]), fl["fat"])
    macro_kcal = out["protein"] * 4 + out["fat"] * 9 + out.get("carbs", 0) * 4
    if macro_kcal > out["kcal"] * 1.05 or macro_kcal < out["kcal"] * 0.95:
        out["carbs"] = max(0.0, round((out["kcal"] - out["protein"] * 4 - out["fat"] * 9) / 4))
    out.setdefault("fiber", round(out["kcal"] / 1000 * 14))
    out.setdefault("water_ml", round(b.weight_kg * 35))
    return out


def body_from_profile(profile, latest_weight: float | None = None) -> BodyData:
    return BodyData(
        sex=profile.sex or "male",
        age=age_from(profile.birth_date),
        height_cm=profile.height_cm or 175,
        weight_kg=latest_weight or profile.weight_kg or 75,
        activity_level=profile.activity_level or "moderate",
        goal=profile.goal or "maintain",
        training_days_per_week=profile.training_days_per_week or 3,
    )


def scale_nutrients(food, grams: float) -> dict[str, Any]:
    f = grams / 100.0
    out = {k: round(getattr(food, k, 0) * f, 2) for k in ("kcal", "protein", "carbs", "fat", "fiber", "sugar", "sat_fat", "salt")}
    out["micros"] = {k: round(v * f, 3) for k, v in (food.micros or {}).items()}
    return out
