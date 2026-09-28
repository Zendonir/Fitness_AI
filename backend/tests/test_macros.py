from datetime import date

import pytest

from app.services.nutrition import BodyData, age_from, bmr_mifflin, compute_targets, floors, validate_targets


def test_mifflin_st_jeor():
    m = BodyData(sex="male", age=30, height_cm=180, weight_kg=80)
    f = BodyData(sex="female", age=30, height_cm=165, weight_kg=60)
    assert bmr_mifflin(m) == pytest.approx(10 * 80 + 6.25 * 180 - 5 * 30 + 5)  # 1780
    assert bmr_mifflin(f) == pytest.approx(10 * 60 + 6.25 * 165 - 5 * 30 - 161)  # 1320.25


def test_age():
    assert age_from(date(1990, 6, 15), date(2026, 6, 14)) == 35
    assert age_from(date(1990, 6, 15), date(2026, 6, 15)) == 36


def test_goals_and_training_days():
    b = BodyData(sex="male", age=30, height_cm=180, weight_kg=80, activity_level="moderate", training_days_per_week=4)
    maintain = compute_targets(b)
    assert maintain["tdee"] == round(1780 * 1.55)
    assert maintain["training"]["kcal"] > maintain["rest"]["kcal"]
    weekly = 4 * maintain["training"]["kcal"] + 3 * maintain["rest"]["kcal"]
    assert weekly == pytest.approx(7 * 1780 * 1.55, rel=0.01)
    bulk = compute_targets(BodyData(**{**b.__dict__, "goal": "bulk"}))
    cut = compute_targets(BodyData(**{**b.__dict__, "goal": "cut"}))
    assert bulk["rest"]["kcal"] > maintain["rest"]["kcal"] > cut["rest"]["kcal"]
    assert cut["training"]["protein"] == 160  # 2,0 g/kg in der Diät


def test_macros_add_up():
    t = compute_targets(BodyData())["rest"]
    assert t["protein"] * 4 + t["carbs"] * 4 + t["fat"] * 9 == pytest.approx(t["kcal"], abs=8)


def test_floors_never_undercut():
    small = BodyData(sex="female", age=60, height_cm=150, weight_kg=45, activity_level="sedentary", goal="cut")
    t = compute_targets(small)
    fl = floors(small)
    assert fl["kcal"] >= 1200
    assert t["rest"]["kcal"] >= fl["kcal"] and t["training"]["kcal"] >= fl["kcal"]
    assert t["rest"]["protein"] >= fl["protein"]


def test_deficit_capped_at_20_percent():
    b = BodyData(sex="male", age=25, height_cm=190, weight_kg=100, activity_level="very_active", goal="cut")
    tdee = bmr_mifflin(b) * 1.9
    crash = validate_targets({"kcal": 1500, "protein": 50, "fat": 20}, b)
    assert crash["kcal"] >= round(tdee * 0.8)
    assert crash["protein"] >= 120
    assert crash["fat"] >= 60


def test_custom_targets_clamped():
    b = BodyData(sex="female", age=30, height_cm=165, weight_kg=60)
    t = compute_targets(b, {"rest": {"kcal": 800}})
    assert t["rest"]["kcal"] >= 1200
