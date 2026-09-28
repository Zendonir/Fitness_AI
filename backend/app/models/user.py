from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import json_field, text_field, ts_field, user_fk


class Role(StrEnum):
    admin = "admin"
    user = "user"
    trainer = "trainer"


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=255)
    display_name: str = Field(default="", max_length=120)
    password_hash: str | None = None
    role: Role = Field(default=Role.user)
    is_active: bool = True
    totp_secret_enc: str | None = None
    totp_enabled: bool = False
    oidc_sub: str | None = Field(default=None, index=True)
    onboarding_done: bool = False
    ai_monthly_limit_usd: float | None = None  # None = globaler Standard
    created_at: datetime = ts_field()
    last_login_at: datetime | None = ts_field(default_now=False)


class UserSettings(SQLModel, table=True):
    __tablename__ = "user_settings"
    user_id: int = Field(foreign_key="user.id", primary_key=True, ondelete="CASCADE")
    data: dict[str, Any] = json_field()


class UserProfile(SQLModel, table=True):
    """Körperdaten & Ernährungsziel für den Makro-Rechner."""

    __tablename__ = "user_profile"
    user_id: int = Field(foreign_key="user.id", primary_key=True, ondelete="CASCADE")
    sex: str = "male"  # male | female
    birth_date: date | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    activity_level: str = "moderate"  # sedentary|light|moderate|active|very_active
    goal: str = "maintain"  # bulk | maintain | cut
    training_days_per_week: int = 3
    # Manuelle Überschreibungen (None = berechnet)
    custom_targets: dict[str, Any] = json_field()


class Session(SQLModel, table=True):
    id: str = Field(primary_key=True)  # SHA-256 des Tokens
    user_id: int = user_fk()
    created_at: datetime = ts_field()
    expires_at: datetime = ts_field()
    user_agent: str = ""
    ip: str = ""


class ApiToken(SQLModel, table=True):
    __tablename__ = "api_token"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    name: str = ""
    token_hash: str = Field(index=True, unique=True)
    prefix: str = ""
    created_at: datetime = ts_field()
    last_used_at: datetime | None = ts_field(default_now=False)


class Invite(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    token_hash: str = Field(index=True, unique=True)
    email: str | None = None
    role: Role = Role.user
    created_by: int | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
    created_at: datetime = ts_field()
    expires_at: datetime = ts_field()
    used_at: datetime | None = ts_field(default_now=False)
    used_by: int | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")


class PasswordReset(SQLModel, table=True):
    __tablename__ = "password_reset"
    id: int | None = Field(default=None, primary_key=True)
    token_hash: str = Field(index=True, unique=True)
    user_id: int = user_fk()
    created_at: datetime = ts_field()
    expires_at: datetime = ts_field()
    used: bool = False


class WebAuthnCredential(SQLModel, table=True):
    __tablename__ = "webauthn_credential"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    credential_id: str = Field(index=True, unique=True)  # base64url
    public_key: str  # base64url
    sign_count: int = 0
    transports: list[str] = json_field(list)
    name: str = "Passkey"
    created_at: datetime = ts_field()
    last_used_at: datetime | None = ts_field(default_now=False)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: int | None = Field(default=None, primary_key=True)
    actor_id: int | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL", index=True)
    action: str = Field(index=True)
    target: str = ""
    details: dict[str, Any] = json_field()
    ip: str = ""
    created_at: datetime = ts_field(index=True)


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_setting"
    key: str = Field(primary_key=True)
    value: Any = json_field(dict, nullable=True)


class TrainerLink(SQLModel, table=True):
    """Benutzer (athlete) gibt seine Daten für einen Trainer frei."""

    __tablename__ = "trainer_link"
    __table_args__ = (UniqueConstraint("trainer_id", "athlete_id"),)
    id: int | None = Field(default=None, primary_key=True)
    trainer_id: int = Field(foreign_key="user.id", index=True, ondelete="CASCADE")
    athlete_id: int = Field(foreign_key="user.id", index=True, ondelete="CASCADE")
    created_at: datetime = ts_field()


class TrainerComment(SQLModel, table=True):
    __tablename__ = "trainer_comment"
    id: int | None = Field(default=None, primary_key=True)
    trainer_id: int = Field(foreign_key="user.id", index=True, ondelete="CASCADE")
    athlete_id: int = Field(foreign_key="user.id", index=True, ondelete="CASCADE")
    target_type: str = "general"  # general|workout|plan|meal_day
    target_id: int | None = None
    text: str = text_field()
    created_at: datetime = ts_field()
    read_at: datetime | None = ts_field(default_now=False)


class ShareGrant(SQLModel, table=True):
    __tablename__ = "share_grant"
    __table_args__ = (UniqueConstraint("resource_type", "resource_id", "user_id"),)
    id: int | None = Field(default=None, primary_key=True)
    resource_type: str = Field(index=True)  # plan|recipe|food|exercise
    resource_id: int = Field(index=True)
    user_id: int = user_fk()
    created_at: datetime = ts_field()


class PushSubscription(SQLModel, table=True):
    __tablename__ = "push_subscription"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    endpoint: str = Field(unique=True)
    p256dh: str
    auth: str
    user_agent: str = ""
    created_at: datetime = ts_field()
