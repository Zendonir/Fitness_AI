"""Der Coach bearbeitet Trainingspläne – auf Wunsch oder als eigener Vorschlag, immer mit Bestätigung."""

import json

from app.ai.providers.base import ToolCall
from app.ai.tools import ToolContext, execute_tool
from app.core.db import session_scope
from app.models import User
from tests.test_ai import _parse_sse, fake_ai  # noqa: F401 - Fixture wiederverwenden


async def _setup(c):
    tpl = next(p for p in (await c.get("/api/plans")).json() if p["name"] == "Upper/Lower 4x")
    return (await c.post(f"/api/plans/{tpl['id']}/activate")).json()


async def _tool(c, name, args):
    async with session_scope() as db:
        u = await db.get(User, c.user["id"])
        ctx = ToolContext(db=db, user=u, consents={"training": True})
        return json.loads(await execute_tool(ctx, ToolCall("x", name, args)))


async def test_structural_changes_keep_supersets_and_history(make_user):
    c = await make_user()
    plan = await _setup(c)
    day3 = plan["days"][2]  # „Oberkörper Volumen“ mit Supersätzen a/b
    assert any(e["superset_group"] for e in day3["exercises"])
    # Workout an Tag 1 → Verknüpfung muss nach der Änderung bestehen bleiben
    w = (await c.post("/api/workouts/start", json={"plan_day_id": plan["days"][0]["id"]})).json()
    out = await _tool(c, "propose_plan_changes", {"reason": "Nur 3 Tage Zeit", "changes": [
        {"op": "remove_day", "day": "Unterkörper Volumen"},
        {"op": "rename_day", "day": "Oberkörper Kraft", "new_name": "Push/Pull Kraft"},
        {"op": "set_weekday", "day": "Unterkörper Kraft", "weekday": "Mi"},
        {"op": "add_day", "day": "Arme & Core", "weekday": "Sa"},
        {"op": "add", "day": "Arme & Core", "new_exercise": "Hammer Curls", "sets": 3, "rep_min": 10, "rep_max": 15},
        {"op": "add", "day": "Arme & Core", "new_exercise": "Trizepsdrücken am Kabel", "superset_group": "a"},
        {"op": "move", "day": "Push/Pull Kraft", "exercise": "Klimmzug", "position": 1},
        {"op": "update", "day": "Oberkörper Volumen", "exercise": "Seitheben", "sets": 5},
        {"op": "set_plan", "weeks": 6, "deload_weeks": [6]},
    ]})
    assert out["status"] == "pending_confirmation"
    # Vor der Bestätigung unverändert
    assert len((await c.get(f"/api/plans/{plan['id']}")).json()["days"]) == 4
    act = next(a for a in (await c.get("/api/coach/actions")).json() if a["id"] == out["action_id"])
    assert act["diff"]["warnings"] == []
    assert (await c.post(f"/api/coach/actions/{act['id']}/confirm")).status_code == 200
    p = (await c.get(f"/api/plans/{plan['id']}")).json()
    names = [d["name"] for d in p["days"]]
    assert names == ["Push/Pull Kraft", "Unterkörper Kraft", "Oberkörper Volumen", "Arme & Core"]
    assert p["weeks"] == 6 and p["deload_weeks"] == [6]
    assert p["days"][0]["id"] == plan["days"][0]["id"]  # Tag-ID bleibt → Workout-Verlauf verknüpft
    assert p["days"][0]["exercises"][0]["exercise"]["name"] == "Klimmzug"
    assert p["days"][1]["weekday"] == 2 and p["days"][3]["weekday"] == 5
    vol = p["days"][2]["exercises"]
    assert next(e for e in vol if e["exercise"]["name"] == "Seitheben")["sets"] == 5
    assert [e["superset_group"] for e in vol] == [e["superset_group"] for e in day3["exercises"]]  # Supersätze erhalten
    arme = p["days"][3]["exercises"]
    assert arme[0]["rep_min"] == 10 and arme[1]["superset_group"] == "a"
    assert (await c.get(f"/api/workouts/{w['id']}")).json()["plan_day_id"] == plan["days"][0]["id"]


async def test_stale_proposal_rejected(make_user):
    c = await make_user()
    plan = await _setup(c)
    out = await _tool(c, "propose_plan_changes", {"changes": [{"op": "update", "day": "Oberkörper Kraft", "exercise": "Bankdrücken", "sets": 5}]})
    # Benutzer ändert den Plan selbst, bevor er den Vorschlag bestätigt
    full = (await c.get(f"/api/plans/{plan['id']}")).json()
    body = {"name": "Umbenannt", "weeks": full["weeks"], "deload_weeks": full["deload_weeks"], "days": [
        {"name": d["name"], "weekday": d["weekday"], "exercises": [
            {k: e[k] for k in ("exercise_id", "sets", "rep_min", "rep_max", "rest_seconds", "superset_group")} for e in d["exercises"]]}
        for d in full["days"]]}
    assert (await c.put(f"/api/plans/{plan['id']}", json=body)).status_code == 200
    r = await c.post(f"/api/coach/actions/{out['action_id']}/confirm")
    assert r.status_code == 409


async def test_invalid_changes_are_reported(make_user):
    c = await make_user()
    await _setup(c)
    out = await _tool(c, "propose_plan_changes", {"changes": [{"op": "add", "day": "Gibt es nicht", "new_exercise": "Bankdrücken"},
                                                              {"op": "add", "day": "Oberkörper Kraft", "new_exercise": "Fantasieübung xyz"}]})
    assert "error" in out and len(out["hinweise"]) == 2


async def test_templates_are_not_modified_directly(make_user):
    c = await make_user()
    out = await _tool(c, "propose_plan_changes", {"plan": "Ganzkörper 3x", "changes": [{"op": "remove_day", "day": "Ganzkörper A"}]})
    assert "error" in out  # keine eigene Kopie → Plan nicht gefunden bzw. Vorlage geschützt


async def test_new_plan_created_and_activated(make_user):
    c = await make_user()
    old = await _setup(c)
    out = await _tool(c, "propose_new_plan", {"name": "Coach 3er-Split", "weeks": 5, "deload_weeks": [5], "activate": True, "days": [
        {"name": "Push", "weekday": "Mo", "exercises": [{"exercise": "Bankdrücken", "sets": 4, "rep_min": 5, "rep_max": 8},
                                                         {"exercise": "Seitheben", "superset_group": "a"}]},
        {"name": "Pull", "weekday": "Mi", "exercises": [{"exercise": "Klimmzug"}, {"exercise": "Unbekannt 123"}]},
        {"name": "Legs", "weekday": "Fr", "exercises": [{"exercise": "Kniebeuge"}]}]})
    assert out["status"] == "pending_confirmation"
    res = (await c.post(f"/api/coach/actions/{out['action_id']}/confirm")).json()["result"]
    assert res["activated"]
    p = (await c.get(f"/api/plans/{res['plan_id']}")).json()
    assert p["is_active"] and p["own"] and [d["name"] for d in p["days"]] == ["Push", "Pull", "Legs"]
    assert p["days"][0]["exercises"][0]["sets"] == 4 and p["days"][0]["weekday"] == 0
    assert len(p["days"][1]["exercises"]) == 1  # unbekannte Übung ausgelassen
    assert not (await c.get(f"/api/plans/{old['id']}")).json()["is_active"]
    today = (await c.get("/api/training/today")).json()
    assert today["plan_id"] == p["id"]


async def test_other_user_cannot_touch_proposal(make_user):
    a = await make_user()
    b = await make_user()
    await _setup(a)
    out = await _tool(a, "propose_plan_changes", {"changes": [{"op": "remove_day", "day": "Unterkörper Volumen"}]})
    assert (await b.post(f"/api/coach/actions/{out['action_id']}/confirm")).status_code == 404
    assert (await b.post(f"/api/coach/actions/{out['action_id']}/reject")).status_code == 404
    # b kann mit dem Tool nur eigene Pläne adressieren
    assert "error" in await _tool(b, "propose_plan_changes", {"changes": [{"op": "remove_day", "day": "Unterkörper Volumen"}]})


async def test_plan_review_endpoint(make_user, fake_ai):  # noqa: F811
    c = await make_user()
    plan = await _setup(c)
    fake_ai.responses["anthropic"] = [
        ToolCall("t1", "get_active_plan", {}),
        ToolCall("t2", "propose_plan_changes", {"reason": "Knie schonen", "changes": [
            {"op": "replace", "day": "Unterkörper Kraft", "exercise": "Kniebeuge", "new_exercise": "Hip Thrust"}]}),
        "Ich schlage vor, Kniebeugen durch Hip Thrusts zu ersetzen.",
    ]
    r = (await c.post("/api/coach/plan-review", json={"plan_id": plan["id"], "request": "Mein Knie zwickt"})).json()
    assert r["actions"][0]["tool"] == "propose_plan_changes" and "Hip Thrust" in r["text"]
    # Nur Plan-Tools stehen zur Verfügung
    tools = {t.name for t in fake_ai.calls[-1]["tools"]}
    assert "propose_plan_changes" in tools and "propose_log_meal" not in tools
    pending = (await c.get(f"/api/coach/actions?plan_id={plan['id']}")).json()
    assert len(pending) == 1


async def test_weekly_job_suggests_plan_changes(make_user, fake_ai):  # noqa: F811
    from app.ai.jobs import suggest_plan_changes

    c = await make_user()
    await _setup(c)
    fake_ai.responses["anthropic"] = [
        ToolCall("t2", "propose_plan_changes", {"reason": "Plateau beim Bankdrücken", "changes": [
            {"op": "update", "day": "Oberkörper Kraft", "exercise": "Bankdrücken", "rep_min": 6, "rep_max": 8}]}),
        "Vorschlag erstellt.",
    ]
    async with session_scope() as db:
        u = await db.get(User, c.user["id"])
        hint = await suggest_plan_changes(db, u)
    assert hint and hint.kind == "plan_suggestion"
    assert (await c.get("/api/coach/actions")).json()[0]["tool"] == "propose_plan_changes"
    # abschaltbar
    await c.patch("/api/me/settings", json={"ai": {"proactive": {"plan_suggestions": False}}})
    async with session_scope() as db:
        u = await db.get(User, c.user["id"])
        assert await suggest_plan_changes(db, u) is None


async def test_duplicate_exercise_rejected(make_user):
    c = await make_user()
    await _setup(c)
    # Beinpresse steht bereits an „Unterkörper Kraft“
    out = await _tool(c, "propose_plan_changes", {"changes": [
        {"op": "replace", "day": "Unterkörper Kraft", "exercise": "Kniebeuge", "new_exercise": "Beinpresse"}]})
    assert "doppelt" in out["error"]
    out = await _tool(c, "propose_plan_changes", {"changes": [
        {"op": "replace", "day": "Unterkörper Kraft", "exercise": "Kniebeuge", "new_exercise": "Hackenschmidt-Kniebeuge"}]})
    assert out["status"] == "pending_confirmation"


async def test_existing_duplicates_do_not_block_other_changes(make_user):
    c = await make_user()
    await _setup(c)
    out = await _tool(c, "propose_plan_changes", {"allow_duplicates": True, "changes": [
        {"op": "replace", "day": "Unterkörper Kraft", "exercise": "Kniebeuge", "new_exercise": "Beinpresse"}]})
    await c.post(f"/api/coach/actions/{out['action_id']}/confirm")
    out = await _tool(c, "propose_plan_changes", {"changes": [{"op": "update", "day": "Oberkörper Kraft", "exercise": "Klimmzug", "sets": 4}]})
    assert out["status"] == "pending_confirmation"
