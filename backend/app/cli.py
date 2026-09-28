"""Kommandozeilenwerkzeuge.

    python -m app.cli gen-keys                       # SECRET_KEY, FERNET_KEY und VAPID-Schlüssel erzeugen
    python -m app.cli create-admin EMAIL PASSWORT    # Admin anlegen (oder bestehenden Benutzer zum Admin machen)
    python -m app.cli reset-link EMAIL               # Passwort-Reset-Link ausgeben
    python -m app.cli init-secrets DIR               # fehlende Schlüssel einmalig in DIR erzeugen (Docker-Init)
    python -m app.cli import-bls [DATEI]             # Bundeslebensmittelschlüssel importieren (ohne Datei: Download)
"""

import asyncio
import base64
import secrets
import sys

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _vapid() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    priv = base64.urlsafe_b64encode(key.private_numbers().private_value.to_bytes(32, "big")).decode().rstrip("=")
    pub = base64.urlsafe_b64encode(key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip("=")
    return pub, priv


def new_keys() -> dict[str, str]:
    pub, priv = _vapid()
    return {
        "secret_key": secrets.token_urlsafe(48),
        "fernet_key": Fernet.generate_key().decode(),
        "vapid_public_key": pub,
        "vapid_private_key": priv,
        "postgres_password": secrets.token_urlsafe(24),
    }


def gen_keys() -> None:
    for k, v in new_keys().items():
        print(f"{k.upper()}={v}")


def init_secrets(directory: str) -> None:
    """Erzeugt nur fehlende Schlüssel – bestehende werden nie überschrieben."""
    import os
    from pathlib import Path

    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    created = []
    fresh = new_keys()
    if (d / "vapid_public_key").exists() != (d / "vapid_private_key").exists():
        sys.exit("VAPID-Schlüssel unvollständig – bitte beide Dateien löschen oder wiederherstellen")
    for name, value in fresh.items():
        f = d / name
        if not f.exists():
            f.write_text(value)
            created.append(name)
        # postgres_password muss für den Postgres-Container (UID 70/999) lesbar sein
        os.chmod(f, 0o644 if name in ("postgres_password", "vapid_public_key") else 0o600)
    print(f"Schlüssel bereit in {d} (neu: {', '.join(created) or 'keine'})")


async def create_admin(email: str, password: str) -> None:
    from sqlmodel import func, select

    from app.core.db import session_scope
    from app.core.security import hash_password, validate_password
    from app.models import Role, User
    from app.services.bootstrap import init_user, seed_database

    if err := validate_password(password):
        sys.exit(err)
    async with session_scope() as db:
        await seed_database(db)
        user = (await db.exec(select(User).where(func.lower(User.email) == email.lower()))).first()
        if user:
            user.role, user.is_active, user.password_hash = Role.admin, True, hash_password(password)
        else:
            user = User(email=email.lower(), display_name="Admin", password_hash=hash_password(password), role=Role.admin)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        await init_user(db, user)
    print(f"Admin {email} bereit.")


async def reset_link(email: str) -> None:
    from sqlmodel import func, select

    from app.api.admin import _reset_link
    from app.core.db import session_scope
    from app.models import User

    async with session_scope() as db:
        user = (await db.exec(select(User).where(func.lower(User.email) == email.lower()))).first()
        if not user:
            sys.exit("Benutzer nicht gefunden")
        print(await _reset_link(db, user))


async def import_bls_cmd(path: str | None) -> None:
    from pathlib import Path

    from app.core.db import session_scope
    from app.services.bls import import_bls

    async with session_scope() as db:
        status = await import_bls(db, path=Path(path) if path else None)
    print(f"BLS importiert: {status['created']} neu, {status['updated']} aktualisiert")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
    elif args[0] == "gen-keys":
        gen_keys()
    elif args[0] == "init-secrets" and len(args) == 2:
        init_secrets(args[1])
    elif args[0] == "import-bls" and len(args) in (1, 2):
        asyncio.run(import_bls_cmd(args[1] if len(args) == 2 else None))
    elif args[0] == "create-admin" and len(args) == 3:
        asyncio.run(create_admin(args[1], args[2]))
    elif args[0] == "reset-link" and len(args) == 2:
        asyncio.run(reset_link(args[1]))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
