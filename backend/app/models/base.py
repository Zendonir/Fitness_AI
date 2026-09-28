from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Text
from sqlmodel import Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def json_field(default_factory=dict, nullable: bool = False) -> Any:
    return Field(default_factory=default_factory, sa_column=Column(JSON, nullable=nullable))


def ts_field(nullable: bool = False, default_now: bool = True, index: bool = False) -> Any:
    if default_now:
        return Field(
            default_factory=utcnow,
            sa_column=Column(DateTime(timezone=True), nullable=nullable, index=index),
        )
    return Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True, index=index))


def text_field(default: str | None = "", nullable: bool = False) -> Any:
    return Field(default=default, sa_column=Column(Text, nullable=nullable))


def user_fk(index: bool = True, nullable: bool = False) -> Any:
    return Field(
        default=None if nullable else ...,
        foreign_key="user.id",
        index=index,
        nullable=nullable,
        ondelete="CASCADE",
    )
