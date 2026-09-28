import os
import tempfile
import uuid

_tmp = tempfile.mkdtemp(prefix="fitforge-test-")
os.environ["DATA_DIR"] = _tmp
os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_tmp}/test.db"))
os.environ["SECRET_KEY"] = "test-secret-key-0123456789"
os.environ["ADMIN_EMAIL"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["PUBLIC_URL"] = "http://testserver"

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import app.models  # noqa: E402,F401
from app.core import db as dbmod  # noqa: E402
from app.main import app  # noqa: E402
from app.services.bootstrap import seed_database  # noqa: E402

PASSWORD = "sehr-sicheres-passwort"


@pytest.fixture(scope="session", autouse=True)
async def database():
    async with dbmod.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    async with dbmod.session_scope() as db:
        await seed_database(db)
    yield
    await dbmod.engine.dispose()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
        headers={"X-Requested-With": "fitforge"},
    )


@pytest.fixture(scope="session")
async def admin_client(database):
    c = _client()
    r = await c.get("/api/auth/config")
    if r.json()["needs_setup"]:
        r = await c.post("/api/auth/register", json={"email": "admin@test.de", "password": PASSWORD, "display_name": "Admin"})
    else:
        r = await c.post("/api/auth/login", json={"email": "admin@test.de", "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "admin"
    yield c
    await c.aclose()


@pytest.fixture
async def make_user(admin_client):
    clients: list[httpx.AsyncClient] = []

    async def factory(role: str = "user") -> httpx.AsyncClient:
        email = f"u{uuid.uuid4().hex[:8]}@test.de"
        inv = await admin_client.post("/api/admin/invites", json={"email": email, "role": role})
        token = inv.json()["url"].split("invite=")[1]
        c = _client()
        r = await c.post("/api/auth/register", json={"email": email, "password": PASSWORD, "invite": token})
        assert r.status_code == 200, r.text
        c.user = r.json()["user"]  # type: ignore[attr-defined]
        clients.append(c)
        return c

    yield factory
    for c in clients:
        await c.aclose()


@pytest.fixture
def anon_client():
    return _client()
