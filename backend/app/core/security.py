import base64
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _ph.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)


def new_token(prefix: str = "", nbytes: int = 32) -> str:
    return prefix + secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    key = settings.fernet_key
    if not key:
        # Fallback: deterministisch aus SECRET_KEY ableiten (nur wenn kein FERNET_KEY gesetzt)
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    return value[:6] + "…" + value[-4:] if len(value) > 12 else "…"


PASSWORD_MIN_LENGTH = 10


def validate_password(pw: str) -> str | None:
    if len(pw) < PASSWORD_MIN_LENGTH:
        return f"Passwort muss mindestens {PASSWORD_MIN_LENGTH} Zeichen lang sein."
    return None
