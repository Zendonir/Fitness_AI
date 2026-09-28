"""KI-Coach: Provider-Abstraktion (Mocks), Fallback, Kostenlimit, Tool-Rechte, Bestätigungen, Chat."""

import json
from types import SimpleNamespace

import pytest

from app.ai import registry
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.base import ChatResult, Message, Provider, ProviderError, ToolCall
from app.ai.providers.openai_provider import OllamaProvider, OpenAIProvider
from app.ai.registry import estimate_cost
from app.ai.tools import TOOL_SPECS, ToolContext, execute_tool


# ------------------------------------------------------------------ Fake-Provider
class Script:
    """Steuert die Antworten der Fake-Provider pro Test."""

    def __init__(self):
        self.responses: dict[str, list] = {"anthropic": [], "openai": []}
        self.calls: list[dict] = []


SCRIPT = Script()


class FakeProvider(Provider):
    name = "fake"

    def to_native(self, messages):
        return [{"role": m.role, "content": m.content} for m in messages]

    async def complete(self, *, system, messages, model, tools=None, temperature=None, max_tokens=4096, on_text=None, json_mode=False):
        SCRIPT.calls.append({"provider": self.name, "system": system, "messages": list(messages), "tools": tools})
        queue = SCRIPT.responses[self.name]
        item = queue.pop(0) if queue else "Ok."
        if isinstance(item, Exception):
            raise item
        if isinstance(item, ToolCall):
            return ChatResult("", [item], 100, 20, model, self.name, "tool_use", raw={"tool": item.name})
        if on_text:
            for part in item.split(" "):
                await on_text(part + " ")
        return ChatResult(item, [], 1000, 200, model, self.name, "end_turn")

    def continuation(self, result, tool_results):
        return [{"role": "assistant", "content": str(result.raw)},
                {"role": "user", "content": [{"tool": c.name, "result": out} for c, out in tool_results]}]

    async def list_models(self):
        return ["fake-1"]


class FakeAnthropic(FakeProvider):
    name = "anthropic"


class FakeOpenAI(FakeProvider):
    name = "openai"


@pytest.fixture
def fake_ai(monkeypatch):
    SCRIPT.responses = {"anthropic": [], "openai": []}
    SCRIPT.calls = []
    monkeypatch.setitem(registry.PROVIDERS, "anthropic", FakeAnthropic)
    monkeypatch.setitem(registry.PROVIDERS, "openai", FakeOpenAI)

    async def creds(db, user_id, provider):
        return ("key", None, "env") if provider in ("anthropic", "openai") else (None, None, "env")

    monkeypatch.setattr(registry, "resolve_credentials", creds)
    return SCRIPT


async def _consent_all(c):
    await c.patch("/api/me/settings", json={"ai": {"consents": {"body": True, "photos": True, "metrics": True,
                                                                "nutrition": True, "training": True}}})


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


# ------------------------------------------------------------------ Provider-Adapter (SDK gemockt)
class _AnthropicStream:
    def __init__(self, final):
        self.final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            for b in self.final.content:
                if b.type == "text":
                    yield SimpleNamespace(type="text", text=b.text)
        return gen()

    async def get_final_message(self):
        return self.final


def _block(**kw):
    ns = SimpleNamespace(**kw)
    ns.model_dump = lambda exclude_none=True: kw
    return ns


async def test_anthropic_adapter_tool_use(monkeypatch):
    final = SimpleNamespace(
        content=[_block(type="text", text="Ich schaue nach."),
                 _block(type="tool_use", id="tu_1", name="get_workouts", input={"days": 7})],
        stop_reason="tool_use", model="claude-opus-5", usage=SimpleNamespace(input_tokens=50, output_tokens=10))
    captured = {}

    class Client:
        messages = SimpleNamespace(stream=lambda **kw: (captured.update(kw), _AnthropicStream(final))[1])

        async def close(self):
            pass

    p = AnthropicProvider(api_key="x")
    monkeypatch.setattr(p, "_client", lambda: Client())
    streamed = []

    async def on_text(t):
        streamed.append(t)

    native = p.to_native([Message("user", "Hi", [{"media_type": "image/jpeg", "data": "AAA"}])])
    assert native[0]["content"][0]["type"] == "image"
    res = await p.complete(system="sys", messages=native, model="claude-opus-5", temperature=0.5, on_text=on_text,
                           tools=[TOOL_SPECS[0]])
    assert "temperature" not in captured and "extra_body" not in captured  # Claude 5 lehnt temperature ab
    assert captured["tools"][0]["input_schema"]["type"] == "object"
    assert res.tool_calls[0].name == "get_workouts" and res.tool_calls[0].arguments == {"days": 7}
    assert streamed == ["Ich schaue nach."] and res.input_tokens == 50
    cont = p.continuation(res, [(res.tool_calls[0], '{"ok":1}')])
    assert cont[0]["role"] == "assistant" and cont[1]["content"][0] == {"type": "tool_result", "tool_use_id": "tu_1", "content": '{"ok":1}'}


async def test_anthropic_refusal_is_provider_error(monkeypatch):
    final = SimpleNamespace(content=[], stop_reason="refusal", model="m", usage=SimpleNamespace(input_tokens=1, output_tokens=0))

    class Client:
        messages = SimpleNamespace(stream=lambda **kw: _AnthropicStream(final))

        async def close(self):
            pass

    p = AnthropicProvider(api_key="x")
    monkeypatch.setattr(p, "_client", lambda: Client())
    with pytest.raises(ProviderError):
        await p.complete(system="s", messages=[], model="m")


async def test_openai_adapter_streams_tool_calls(monkeypatch):
    def chunk(content=None, tool=None, finish=None, usage=None):
        delta = SimpleNamespace(content=content, tool_calls=[tool] if tool else None)
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)] if not usage else [], usage=usage)

    chunks = [
        chunk(content="Hallo "),
        chunk(tool=SimpleNamespace(index=0, id="c1", function=SimpleNamespace(name="get_", arguments='{"da'))),
        chunk(tool=SimpleNamespace(index=0, id=None, function=SimpleNamespace(name="workouts", arguments='ys": 3}'))),
        chunk(finish="tool_calls"),
        chunk(usage=SimpleNamespace(prompt_tokens=30, completion_tokens=5)),
    ]
    captured = {}

    async def create(**kw):
        captured.update(kw)

        async def gen():
            for c in chunks:
                yield c
        return gen()

    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        async def close(self):
            pass

    p = OpenAIProvider(api_key="x")
    monkeypatch.setattr(p, "_client", lambda: Client())
    res = await p.complete(system="sys", messages=[{"role": "user", "content": "x"}], model="gpt-5", temperature=0.7)
    assert "temperature" not in captured and captured["max_completion_tokens"] == 4096
    assert captured["messages"][0] == {"role": "system", "content": "sys"}
    assert res.text == "Hallo " and res.tool_calls[0].name == "get_workouts" and res.tool_calls[0].arguments == {"days": 3}
    assert (res.input_tokens, res.output_tokens) == (30, 5)
    cont = p.continuation(res, [(res.tool_calls[0], "{}")])
    assert cont[1] == {"role": "tool", "tool_call_id": "c1", "content": "{}"}
    o = OllamaProvider(base_url="http://ollama:11434")
    assert o.base_url.endswith("/v1") and not o.uses_max_completion_tokens


def test_cost_estimation():
    assert estimate_cost("anthropic", "claude-opus-5", 1_000_000, 1_000_000) == 30.0
    assert estimate_cost("anthropic", "claude-sonnet-5", 1_000_000, 0) == 2.0
    assert estimate_cost("openai", "gpt-5-mini", 1_000_000, 1_000_000) == 2.25
    assert estimate_cost("ollama", "llama3.1", 10**9, 10**9) == 0
    assert estimate_cost("openai", "gpt-5", 1_000_000, 0, {"gpt-5": [9, 9]}) == 9


# ------------------------------------------------------------------ Chat Ende-zu-Ende
async def test_chat_streams_and_logs_usage(make_user, fake_ai, admin_client):
    c = await make_user()
    await _consent_all(c)
    fake_ai.responses["anthropic"] = ["Du machst das super!"]
    r = await c.post("/api/coach/chat", json={"message": "Wie läuft es?"})
    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "meta" and "text" in kinds and kinds[-1] == "done"
    assert "".join(d["delta"] for e, d in events if e == "text").strip() == "Du machst das super!"
    conv_id = events[0][1]["conversation_id"]
    conv = (await c.get(f"/api/coach/conversations/{conv_id}")).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    status = (await c.get("/api/coach/status")).json()
    assert status["month_cost_usd"] > 0
    usage = (await admin_client.get("/api/admin/ai-usage")).json()["rows"]
    assert any(row["user_id"] == c.user["id"] and row["provider"] == "anthropic" for row in usage)
    # Systemprompt enthält Leitplanken und Untergrenzen
    assert "Keine medizinischen Diagnosen" in fake_ai.calls[0]["system"]


async def test_fallback_to_second_provider(make_user, fake_ai):
    c = await make_user()
    fake_ai.responses["anthropic"] = [ProviderError("Rate-Limit", status=429)]
    fake_ai.responses["openai"] = ["Antwort von OpenAI"]
    r = await c.post("/api/coach/chat", json={"message": "Hallo"})
    events = _parse_sse(r.text)
    assert any(e == "fallback" for e, _ in events)
    done = next(d for e, d in events if e == "done")
    assert done["provider"] == "openai"


async def test_fallback_can_be_disabled(make_user, fake_ai):
    c = await make_user()
    await c.patch("/api/me/settings", json={"ai": {"fallback": False}})
    fake_ai.responses["anthropic"] = [ProviderError("down")]
    r = await c.post("/api/coach/chat", json={"message": "Hallo"})
    assert any(e == "error" for e, _ in _parse_sse(r.text))


async def test_task_routing(make_user, fake_ai):
    c = await make_user()
    await c.patch("/api/me/settings", json={"ai": {"task_routing": {"chat": {"provider": "openai", "model": "gpt-x"}}}})
    fake_ai.responses["openai"] = ["via openai"]
    r = await c.post("/api/coach/chat", json={"message": "Hallo"})
    done = next(d for e, d in _parse_sse(r.text) if e == "done")
    assert done["provider"] == "openai" and done["model"] == "gpt-x"


async def test_cost_limit_blocks(make_user, fake_ai, admin_client):
    c = await make_user()
    await admin_client.patch(f"/api/admin/users/{c.user['id']}", json={"ai_monthly_limit_usd": 0.02})
    fake_ai.responses["anthropic"] = ["erste Antwort"]  # kostet 1000/200 Tokens Opus = 0.01 $
    await c.post("/api/coach/chat", json={"message": "1"})
    fake_ai.responses["anthropic"] = ["zweite"]
    await c.post("/api/coach/chat", json={"message": "2"})
    r = await c.post("/api/coach/chat", json={"message": "3"})
    assert any(e == "error" and "Budget" in d["message"] for e, d in _parse_sse(r.text))


async def test_ai_can_be_disabled_globally(make_user, fake_ai, admin_client):
    c = await make_user()
    await admin_client.patch("/api/admin/settings", json={"ai_enabled": False})
    try:
        r = await c.post("/api/coach/chat", json={"message": "Hallo"})
        assert r.status_code == 409
        # App bleibt ohne KI nutzbar
        assert (await c.get("/api/stats/today")).status_code == 200
    finally:
        await admin_client.patch("/api/admin/settings", json={"ai_enabled": True})


async def test_user_can_disable_ai(make_user, fake_ai):
    c = await make_user()
    await c.patch("/api/me/settings", json={"ai": {"enabled": False}})
    assert (await c.post("/api/coach/chat", json={"message": "x"})).status_code == 409


# ------------------------------------------------------------------ Tool-Rechte
async def test_tool_loop_and_pending_action(make_user, fake_ai):
    c = await make_user()
    await _consent_all(c)
    fake_ai.responses["anthropic"] = [
        ToolCall("t1", "get_nutrition", {"days": 3}),
        ToolCall("t2", "propose_log_meal", {"slot": "Abendessen", "items": [
            {"name": "Skyr", "grams": 250, "kcal": 160, "protein": 28, "carbs": 10, "fat": 0.5}]}),
        "Ich habe dir Skyr vorgeschlagen – bitte bestätigen.",
    ]
    r = await c.post("/api/coach/chat", json={"message": "Was esse ich heute Abend?"})
    events = _parse_sse(r.text)
    action = next(d for e, d in events if e == "action")
    assert action["tool"] == "propose_log_meal" and action["status"] == "pending"
    # nichts geloggt bis zur Bestätigung
    assert (await c.get("/api/meals")).json()["totals"]["kcal"] == 0
    other = await make_user()
    assert (await other.post(f"/api/coach/actions/{action['id']}/confirm")).status_code == 404
    assert (await c.post(f"/api/coach/actions/{action['id']}/confirm")).json()["status"] == "confirmed"
    assert (await c.get("/api/meals")).json()["totals"]["protein"] == 28
    assert (await c.post(f"/api/coach/actions/{action['id']}/confirm")).status_code == 409


async def test_tools_only_see_own_data(make_user):
    """Coach sieht nur Daten des anfragenden Benutzers – es gibt keinen user_id-Parameter."""
    from app.core.db import session_scope
    from app.models import User

    a = await make_user()
    b = await make_user()
    await a.post("/api/meals", json={"name": "Geheimes Essen", "kcal": 999, "protein": 1})
    ex = (await a.get("/api/exercises")).json()[0]
    await a.post("/api/workouts", json={"name": "A-Training", "sets": [{"exercise_id": ex["id"], "reps": 5, "weight_kg": 200}]})
    await a.post("/api/metrics", json={"name": "Geheimmetrik"})
    all_consent = {"body": True, "metrics": True, "nutrition": True, "training": True}
    async with session_scope() as db:
        ub = await db.get(User, b.user["id"])
        ctx = ToolContext(db=db, user=ub, consents=all_consent)
        for name, args in [("get_nutrition", {"days": 3}), ("get_workouts", {"days": 3}), ("get_metrics", {}),
                           ("get_today_status", {}), ("search_foods", {"query": "Geheim"}),
                           ("get_personal_records", {}), ("get_training_volume", {"days": 3}),
                           # Versuch, eine fremde ID einzuschleusen, wird ignoriert
                           ("get_workouts", {"days": 3, "user_id": a.user["id"]})]:
            out = await execute_tool(ctx, ToolCall("x", name, args))
            assert "Geheim" not in out and "999" not in out and "A-Training" not in out and "200kg" not in out, (name, out)


async def test_tools_respect_consents(make_user):
    from app.core.db import session_scope
    from app.models import User

    c = await make_user()
    async with session_scope() as db:
        u = await db.get(User, c.user["id"])
        ctx = ToolContext(db=db, user=u, consents={"nutrition": False, "body": False, "metrics": False, "training": True})
        for name in ("get_nutrition", "get_weight_trend", "get_metrics", "propose_log_weight"):
            out = json.loads(await execute_tool(ctx, ToolCall("x", name, {"weight_kg": 80})))
            assert "nicht für die KI freigegeben" in out["error"], name


async def test_nutrition_goal_tool_enforces_floors(make_user):
    from app.core.db import session_scope
    from app.models import User

    c = await make_user()
    await c.put("/api/me/profile", json={"sex": "female", "height_cm": 165, "weight_kg": 60, "birth_date": "1990-01-01"})
    async with session_scope() as db:
        u = await db.get(User, c.user["id"])
        ctx = ToolContext(db=db, user=u, consents={"nutrition": True})
        out = json.loads(await execute_tool(ctx, ToolCall("x", "propose_nutrition_goal",
                                                          {"goal": "cut", "rest": {"kcal": 900, "protein": 40}})))
        aid = out["action_id"]
    actions = (await c.get("/api/coach/actions")).json()
    act = next(a for a in actions if a["id"] == aid)
    assert act["diff"]["clamped"] is True
    assert act["diff"]["after"]["rest"]["kcal"] >= 1200 and act["diff"]["after"]["rest"]["protein"] >= 60
    await c.post(f"/api/coach/actions/{aid}/confirm")
    t = (await c.get("/api/me/targets")).json()
    assert t["rest"]["kcal"] >= t["floors"]["kcal"]


async def test_plan_change_diff_and_apply(make_user):
    from app.core.db import session_scope
    from app.models import User

    c = await make_user()
    tpl = next(p for p in (await c.get("/api/plans")).json() if p["name"] == "Ganzkörper 3x")
    plan = (await c.post(f"/api/plans/{tpl['id']}/activate")).json()
    day = plan["days"][0]
    first = day["exercises"][0]["exercise"]["name"]
    async with session_scope() as db:
        u = await db.get(User, c.user["id"])
        ctx = ToolContext(db=db, user=u, consents={"training": True})
        out = json.loads(await execute_tool(ctx, ToolCall("x", "propose_plan_changes", {"reason": "Knie", "changes": [
            {"op": "replace", "day": day["name"], "exercise": first, "new_exercise": "Beinpresse"},
            {"op": "update", "day": day["name"], "exercise": "Bankdrücken", "sets": 5}]})))
    act = next(a for a in (await c.get("/api/coach/actions")).json() if a["id"] == out["action_id"])
    assert act["diff"]["before"][0]["exercises"][0]["exercise"] == first
    assert act["diff"]["after"][0]["exercises"][0]["exercise"] == "Beinpresse"
    await c.post(f"/api/coach/actions/{act['id']}/confirm")
    updated = (await c.get(f"/api/plans/{plan['id']}")).json()
    names = [e["exercise"]["name"] for e in updated["days"][0]["exercises"]]
    assert names[0] == "Beinpresse"
    assert next(e for e in updated["days"][0]["exercises"] if e["exercise"]["name"] == "Bankdrücken")["sets"] == 5


async def test_memory_tool_and_notes(make_user):
    from app.core.db import session_scope
    from app.models import User

    c = await make_user()
    async with session_scope() as db:
        u = await db.get(User, c.user["id"])
        ctx = ToolContext(db=db, user=u)
        await execute_tool(ctx, ToolCall("x", "save_memory", {"content": "Mag keinen Fisch", "category": "preference"}))
        again = json.loads(await execute_tool(ctx, ToolCall("x", "save_memory", {"content": "mag keinen fisch"})))
    assert again["status"] == "already_known"
    notes = (await c.get("/api/coach/notes")).json()
    assert len(notes) == 1 and notes[0]["source"] == "coach"
    assert (await c.delete(f"/api/coach/notes/{notes[0]['id']}")).status_code == 200
    other = await make_user()
    assert (await other.get("/api/coach/notes")).json() == []


async def test_context_includes_memory_and_respects_consent(make_user, fake_ai):
    c = await make_user()
    await c.post("/api/coach/notes", json={"content": "Trainiert morgens vor der Arbeit", "importance": 3})
    await c.put("/api/me/profile", json={"sex": "male", "height_cm": 187, "weight_kg": 91})
    await c.post("/api/coach/chat", json={"message": "Hi"})
    system = fake_ai.calls[-1]["system"]
    assert "Trainiert morgens" in system
    assert "187" not in system  # Körperwerte ohne Freigabe nicht gesendet
    await _consent_all(c)
    await c.post("/api/coach/chat", json={"message": "Hi"})
    assert "187" in fake_ai.calls[-1]["system"]


async def test_photo_requires_consent(make_user, fake_ai):
    c = await make_user()
    r = await c.post("/api/coach/vision/meal", files={"file": ("a.jpg", b"123", "image/jpeg")})
    assert r.status_code == 403


async def test_reports_and_hints_without_ai(make_user, admin_client):
    c = await make_user()
    await admin_client.patch("/api/admin/settings", json={"ai_enabled": False})
    try:
        rep = (await c.post("/api/coach/reports/week")).json()
        assert rep["data"]["report"]["generated_by"] == "rules" and rep["data"]["report"]["recommendations"]
        assert (await c.post("/api/coach/hints/check")).status_code == 200
    finally:
        await admin_client.patch("/api/admin/settings", json={"ai_enabled": True})


async def test_weekly_report_with_ai(make_user, fake_ai):
    c = await make_user()
    fake_ai.responses["anthropic"] = ['```json\n{"score": 8, "headline": "Starke Woche", "summary": "Gut.", '
                                      '"highlights": [], "improvements": [], "recommendations": ["Mehr schlafen"]}\n```']
    rep = (await c.post("/api/coach/reports/week")).json()
    assert rep["data"]["report"]["score"] == 8 and rep["data"]["report"]["generated_by"] == "ai"
    week = (await c.get("/api/reports/week")).json()
    assert week["coach"]["data"]["report"]["headline"] == "Starke Woche"
