"""Bundeslebensmittelschlüssel-Import und Suche nach Gerichten wie Döner."""

import io

import pytest
from openpyxl import Workbook

from app.services.bls import portion_for
from tests.test_ai import fake_ai  # noqa: F401

NUTRIENTS = [
    "ENERCJ Energie (Kilojoule) [kJ/100g]", "ENERCC Energie (Kilokalorien) [kcal/100g]", "PROT625 Protein (Nx6,25) [g/100g]",
    "FAT Fett [g/100g]", "CHO Kohlenhydrate, verfügbar [g/100g]", "SUGAR Zucker (Mono- und Disaccharide), gesamt [g/100g]",
    "FIBT Ballaststoffe, gesamt [g/100g]", "FASAT Fettsäuren, gesättigt [g/100g]", "NA Natrium [mg/100g]",
    "CA Calcium [mg/100g]", "VITD Vitamin D [µg/100g]",
]
ROWS = [
    ("Y921162", "Döner Kebab, Fladenbrot gefüllt mit Grillfleisch (Geflügel), Rohkost und Sauce", "Doner kebab (poultry)",
     [833, 199, 11.5, 7.6, 18, 2.1, 1.9, 1.8, 420, 40, "<LOD or <LOQ"]),
    ("Y9A1040", "Döner vegetarisch, Fladenbrot gefüllt mit Rohkost, Schafskäse und Sauce", "Doner vegetarian",
     [790, 189, 7.2, 8.9, 19.5, 2.4, 2.2, 3.9, 510, 120, 0.1]),
    ("C133000", "Hafer Flocken", "Oat flakes", [1465, 348, 13.5, 7.0, 53.3, 0.74, 10.0, 1.3, 2, 48, "-"]),
    ("Y384112", "Gyros (Schweinefleisch) gebraten", "Gyros (pork) fried", [961, 230, 24, 14.5, 0.5, 0.5, 0, 5.3, 600, 12, 0.3]),
]


def bls_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    header = ["BLS Code", "Lebensmittelbezeichnung", "Food name"]
    for n in NUTRIENTS:  # wie im Original: Wert, Datenquelle, Referenz
        header += [n, n.split(" ")[0] + " Datenquelle", n.split(" ")[0] + " Referenz"]
    ws.append(header)
    for code, de, en, vals in ROWS:
        row = [code, de, en]
        for v in vals:
            row += [v, "Analyse", "Ref"]
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def no_off(monkeypatch):
    calls = []

    async def fake_search(db, q, limit=20):
        calls.append(q)
        return []

    monkeypatch.setattr("app.api.nutrition.search_off", fake_search)
    return calls


async def _import(admin_client):
    r = await admin_client.post("/api/admin/food-db/bls/upload",
                                files={"file": ("BLS_4_0_Daten_2025_DE.xlsx", bls_xlsx(), "application/octet-stream")})
    assert r.status_code == 200, r.text
    return r.json()


async def test_bls_upload_import_and_idempotent(admin_client):
    first = await _import(admin_client)
    assert first["count"] == 4
    again = await _import(admin_client)
    assert again["updated"] == 4 and again["created"] == 0
    status = (await admin_client.get("/api/admin/food-db")).json()
    assert status["counts"]["bls"] == 4 and "Max Rubner-Institut" in status["bls"]["attribution"]


async def test_upload_rejects_wrong_file(admin_client):
    r = await admin_client.post("/api/admin/food-db/bls/upload", files={"file": ("x.csv", b"a;b;c\n1;2;3\n", "text/csv")})
    assert r.status_code == 422


async def test_search_finds_doener_first_and_logs(admin_client, make_user, no_off):
    await _import(admin_client)
    c = await make_user()
    await c.post("/api/foods", json={"name": "Hafer Flocken (meine Marke)", "kcal": 360, "protein": 14})
    for q in ("Döner", "doener", "döner kebab"):
        res = (await c.get("/api/foods/search", params={"q": q})).json()["results"]
        assert res and res[0]["source"] == "bls" and "Döner" in res[0]["name"], q
    d = (await c.get("/api/foods/search", params={"q": "döner geflügel"})).json()["results"]
    assert len(d) == 1 and d[0]["protein"] == 11.5 and d[0]["serving_g"] == 380 and d[0]["serving_label"] == "1 Döner"
    assert d[0]["salt"] == pytest.approx(1.05) and d[0]["micros"]["calcium_mg"] == 40
    assert d[0]["category"] == "Gerichte & Snacks"
    # eigene Lebensmittel zuerst
    oats = (await c.get("/api/foods/search", params={"q": "hafer"})).json()["results"]
    assert oats[0]["own"] and oats[1]["source"] == "bls"
    # Portion loggen: 1 Döner = 380 g
    m = (await c.post("/api/meals", json={"food_id": d[0]["id"], "grams": 380})).json()
    assert m["kcal"] == pytest.approx(199 * 3.8, abs=0.5)
    # genug lokale Treffer → Open Food Facts wird nicht abgefragt
    no_off.clear()
    await c.get("/api/foods/search", params={"q": "gyros"})
    assert no_off == ["gyros"]  # nur 1 lokaler Treffer → OFF ergänzt


def test_portion_heuristics():
    assert portion_for("Döner Kebab, Fladenbrot")[0] == 380
    assert portion_for("Pizza Margherita")[0] == 380
    assert portion_for("Pizzabaguette mit Käse")[0] == 125
    assert portion_for("Quark")[0] is None


async def test_ai_estimate_food(make_user, fake_ai):  # noqa: F811
    c = await make_user()
    fake_ai.responses["anthropic"] = ['{"items": [{"name": "Dürüm Hähnchen", "grams": 400, "kcal": 780, "protein": 42, '
                                      '"carbs": 70, "fat": 34, "confidence": "mittel"}], "note": "Typische Imbissportion"}']
    r = (await c.post("/api/coach/estimate-food", json={"text": "Dürüm mit Hähnchen und Knoblauchsoße"})).json()
    assert r["result"]["items"][0]["kcal"] == 780
