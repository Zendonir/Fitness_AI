"""Kommandozeilenwerkzeuge.

    python -m app.cli gen-keys                       # SECRET_KEY, FERNET_KEY und VAPID-Schlüssel erzeugen
    python -m app.cli create-admin EMAIL PASSWORT    # Admin anlegen (oder bestehenden Benutzer zum Admin machen)
    python -m app.cli reset-link EMAIL               # Passwort-Reset-Link ausgeben
"""

import asyncio
import base64
import secrets
import sys

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def gen_keys() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    priv = base64.urlsafe_b64encode(key.private_numbers().private_value.to_bytes(32, "big")).decode().rstrip("=")
    pub = base64.urlsafe_b64encode(key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip("=")
    print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
    print(f"FERNET_KEY={Fernet.generate_key().decode()}")
    print(f"VAPID_PUBLIC_KEY={pub}")
    print(f"VAPID_PRIVATE_KEY={priv}")
    print(f"POSTGRES_PASSWORD={secrets.token_urlsafe(24)}")


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


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
    elif args[0] == "gen-keys":
        gen_keys()
    elif args[0] == "create-admin" and len(args) == 3:
        asyncio.run(create_admin(args[1], args[2]))
    elif args[0] == "reset-link" and len(args) == 2:
        asyncio.run(reset_link(args[1]))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
