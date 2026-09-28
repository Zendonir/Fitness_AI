from datetime import date, timedelta

import pytest

from app.services import off


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    async def fake_search(db, q, limit=20):
        return []

    async def fake_lookup(db, code):
        return None

    monkeypatch.setattr("app.api.nutrition.search_off", fake_search)
    monkeypatch.setattr("app.api.nutrition.lookup_barcode", fake_lookup)


def test_off_product_mapping():
    p = {"code": "4000", "product_name": "Magerquark", "brands": "Milsani, Aldi",
         "nutriments": {"energy-kcal_100g": 67, "proteins_100g": 12, "carbohydrates_100g": 4, "fat_100g": 0.2,
                        "calcium_100g": 0.12}, "serving_quantity": "250"}
    f = off.product_to_food(p)
    assert f["name"] == "Magerquark" and f["brand"] == "Milsani" and f["protein"] == 12
    assert f["micros"]["calcium_mg"] == 120 and f["serving_g"] == 250
    assert off.product_to_food({"nutriments": {}}) is None


async def test_meal_log_recipe_and_copy(make_user):
    c = await make_user()
    await c.put("/api/me/profile", json={"sex": "male", "height_cm": 180, "weight_kg": 80, "birth_date": "1995-01-01"})
    quark = (await c.post("/api/foods", json={"name": "Quark", "kcal": 67, "protein": 12, "carbs": 4, "fat": 0.2})).json()
    oats = (await c.post("/api/foods", json={"name": "Haferflocken", "kcal": 370, "protein": 13, "carbs": 59, "fat": 7, "fiber": 10})).json()
    r = (await c.post("/api/recipes", json={"name": "Overnight Oats", "servings": 2, "ingredients": [
        {"food_id": quark["id"], "grams": 500}, {"food_id": oats["id"], "grams": 100}]})).json()
    assert r["total"]["protein"] == 73 and r["per_serving"]["protein"] == 36.5 and r["serving_grams"] == 300
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    await c.post("/api/meals", json={"day": yesterday, "slot": "Frühstück", "recipe_id": r["id"], "servings": 1})
    await c.post("/api/meals", json={"day": yesterday, "slot": "Snacks", "food_id": quark["id"], "grams": 250})
    await c.post("/api/meals", json={"day": yesterday, "slot": "Snacks", "name": "Apfel", "kcal": 80, "carbs": 19})
    day = (await c.get("/api/meals", params={"day": yesterday})).json()
    assert day["totals"]["protein"] == pytest.approx(36.5 + 30, abs=0.2)
    assert day["targets"]["kcal"] > 1500
    assert (await c.post("/api/meals/copy", json={})).json()["copied"] == 3
    today = (await c.get("/api/meals")).json()
    assert today["totals"]["kcal"] == day["totals"]["kcal"]
    # Portion ändern
    entry = today["slots"][0]["entries"][0]
    upd = (await c.patch(f"/api/meals/{entry['id']}", json={"servings": 2})).json()
    assert upd["protein"] == pytest.approx(73, abs=0.2)


async def test_water_templates_favorites(make_user):
    c = await make_user()
    await c.post("/api/water", json={"ml": 500})
    await c.post("/api/water", json={"ml": 250, "client_id": "w1"})
    await c.post("/api/water", json={"ml": 250, "client_id": "w1"})
    assert (await c.get("/api/meals")).json()["water_ml"] == 750
    await c.delete("/api/water/last")
    assert (await c.get("/api/meals")).json()["water_ml"] == 500
    f = (await c.post("/api/foods", json={"name": "Reis", "kcal": 350})).json()
    fav = (await c.post("/api/favorites", json={"food_id": f["id"]})).json()
    assert (await c.get("/api/favorites")).json()[0]["food"]["name"] == "Reis"
    await c.post("/api/meals", json={"food_id": f["id"], "grams": 100})
    t = (await c.post("/api/day-templates", json={"name": "Standard", "from_day": date.today().isoformat()})).json()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    await c.post(f"/api/day-templates/{t['id']}/apply", params={"day": tomorrow})
    assert (await c.get("/api/meals", params={"day": tomorrow})).json()["totals"]["kcal"] == 350
    assert (await c.delete(f"/api/favorites/{fav['id']}")).status_code == 200


async def test_nutrition_isolated(make_user):
    a = await make_user()
    b = await make_user()
    f = (await a.post("/api/foods", json={"name": "Geheim", "kcal": 1})).json()
    m = (await a.post("/api/meals", json={"food_id": f["id"], "grams": 50})).json()
    assert (await b.get(f"/api/foods/{f['id']}")).status_code == 404
    assert (await b.post("/api/meals", json={"food_id": f["id"]})).status_code == 404
    assert (await b.delete(f"/api/meals/{m['id']}")).status_code == 404
    assert (await b.patch(f"/api/meals/{m['id']}", json={"grams": 1})).status_code == 404
    assert (await b.get("/api/meals")).json()["totals"]["kcal"] == 0
    res = (await b.get("/api/foods/search", params={"q": "Geheim"})).json()["results"]
    assert res == []
    r = (await a.post("/api/recipes", json={"name": "R", "ingredients": [{"food_id": f["id"], "grams": 10}]})).json()
    assert (await b.get(f"/api/recipes/{r['id']}")).status_code == 404
    # b darf fremdes Lebensmittel nicht in eigenes Rezept packen
    assert (await b.post("/api/recipes", json={"name": "X", "ingredients": [{"food_id": f["id"], "grams": 10}]})).status_code == 404


async def test_body_and_metrics(make_user):
    c = await make_user()
    for i, w in enumerate([80.0, 79.6, 79.8, 79.2]):
        await c.post("/api/body", json={"day": (date.today() - timedelta(days=3 - i)).isoformat(), "weight_kg": w})
    body = (await c.get("/api/body")).json()
    assert body["latest"]["weight_kg"] == 79.2
    assert body["weight_trend"][-1]["avg"] == pytest.approx((80 + 79.6 + 79.8 + 79.2) / 4, abs=0.01)
    m = (await c.post("/api/metrics", json={"name": "Schlaf", "kind": "scale", "scale_min": 1, "scale_max": 10})).json()
    assert (await c.post("/api/metrics/entries", json={"metric_id": m["id"], "value": 11})).status_code == 422
    await c.post("/api/metrics/entries", json={"metric_id": m["id"], "value": 7})
    await c.post("/api/metrics/entries", json={"metric_id": m["id"], "value": 8})  # gleicher Tag -> überschreibt
    entries = (await c.get(f"/api/metrics/{m['id']}/entries")).json()
    assert len(entries) == 1 and entries[0]["value_num"] == 8
    other = await make_user()
    assert (await other.post("/api/metrics/entries", json={"metric_id": m["id"], "value": 5})).status_code == 404
    assert (await other.get(f"/api/metrics/{m['id']}/entries")).status_code == 404


async def test_photo_upload_strips_and_isolated(make_user):
    import io

    from PIL import Image

    c = await make_user()
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), "red").save(buf, "PNG")
    p = (await c.post("/api/photos", files={"file": ("a.png", buf.getvalue(), "image/png")}, data={"pose": "side"})).json()
    r = await c.get(p["url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(r.content))
    assert max(img.size) == 1600
    other = await make_user()
    assert (await other.get(p["url"])).status_code == 404
