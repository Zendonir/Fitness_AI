from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_MEDIA_BASE = "https://cdn.jsdelivr.net/gh/JahelCuadrado/ExerciseGymGifsDB@v1.2.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FitForge"
    public_url: str = ""  # leer = aus Anfrage ableiten (Reverse Proxy)
    secret_key: str = Field(default="dev-secret-change-me", min_length=16)
    fernet_key: str = ""  # Master-Key für verschlüsselte API-Keys / TOTP-Secrets
    tz: str = "Europe/Berlin"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://fitforge:fitforge@localhost:5432/fitforge"
    redis_url: str = "redis://localhost:6379/0"

    data_dir: Path = Path("/data")
    frontend_dir: Path = Path(__file__).resolve().parents[3] / "frontend" / "build"

    session_days: int = 30
    cookie_secure: bool | None = None  # None = aus public_url ableiten

    # Erster Admin (wird beim Start angelegt, falls noch kein Benutzer existiert)
    admin_email: str = ""
    admin_password: str = ""

    # KI (global, optional – können auch im Admin-Panel gesetzt werden)
    ai_enabled: bool = True
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = ""
    default_ai_provider: str = "anthropic"
    default_anthropic_model: str = "claude-opus-5"
    default_openai_model: str = "gpt-5"
    default_ollama_model: str = "llama3.1"
    ai_default_monthly_limit_usd: float = 10.0
    ai_context_token_budget: int = 12000

    # Web Push
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # OIDC (optional)
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_display_name: str = "SSO"
    oidc_auto_create: bool = False
    oidc_admin_group: str = ""

    # WebAuthn
    webauthn_rp_id: str = ""  # Default: Hostname aus public_url
    webauthn_rp_name: str = "FitForge"

    # Backups
    backup_keep_daily: int = 7
    backup_keep_weekly: int = 4
    backup_keep_monthly: int = 6
    backup_hour: int = 3

    open_food_facts_url: str = "https://world.openfoodfacts.org"
    # Bundeslebensmittelschlüssel beim ersten Start herunterladen
    bls_auto_import: bool = True
    # Übungsanimationen (ExerciseGymGifsDB). Leer = jsDelivr-CDN; eigener Spiegel möglich (gleiche Ordnerstruktur)
    exercise_media_base: str = ""
    off_user_agent: str = "FitForge/1.0 (self-hosted)"

    @property
    def media_base(self) -> str:
        return (self.exercise_media_base or DEFAULT_MEDIA_BASE).rstrip("/")

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.public_url.startswith("https://")

    @property
    def rp_id(self) -> str:
        if self.webauthn_rp_id:
            return self.webauthn_rp_id
        from urllib.parse import urlparse

        return urlparse(self.public_url).hostname or "localhost"

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
