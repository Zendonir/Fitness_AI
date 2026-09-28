"""Öffentliche Basis-URL: aus PUBLIC_URL oder – wenn nicht gesetzt – aus der Anfrage (Reverse Proxy)."""

from urllib.parse import urlparse

from fastapi import Request

from app.core.config import settings


def base_url(request: Request | None = None) -> str:
    if settings.public_url:
        return settings.public_url.rstrip("/")
    if request is None:
        return ""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}"


def rp_id(request: Request) -> str:
    return settings.webauthn_rp_id or urlparse(base_url(request)).hostname or "localhost"


def secure_cookies(request: Request) -> bool:
    if settings.cookie_secure is not None:
        return settings.cookie_secure
    return base_url(request).startswith("https://")
