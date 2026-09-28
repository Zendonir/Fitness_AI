from datetime import date, datetime
from typing import Any

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import json_field, text_field, ts_field, user_fk


class CoachProfile(SQLModel, table=True):
    __tablename__ = "coach_profile"
    user_id: int = Field(foreign_key="user.id", primary_key=True, ondelete="CASCADE")
    goals: str = text_field()
    experience: str = "intermediate"  # beginner|intermediate|advanced
    preferences: str = text_field()
    dislikes: str = text_field()
    limitations: str = text_field()
    equipment: str = text_field()
    schedule: str = text_field()
    extra: dict[str, Any] = json_field()
    updated_at: datetime = ts_field()


class CoachNote(SQLModel, table=True):
    __tablename__ = "coach_note"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    content: str = text_field()
    category: str = "general"  # general|training|nutrition|health|preference|goal
    importance: int = 2  # 1-3
    source: str = "coach"  # coach|user
    created_at: datetime = ts_field()


class CoachSummary(SQLModel, table=True):
    __tablename__ = "coach_summary"
    __table_args__ = (UniqueConstraint("user_id", "period", "period_start"),)
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    period: str = Field(index=True)  # day|week|month
    period_start: date = Field(index=True)
    content: str = text_field()
    data: dict[str, Any] = json_field()  # Kennzahlen + (Woche) Bericht mit Bewertung/Empfehlungen
    created_at: datetime = ts_field()


class ChatConversation(SQLModel, table=True):
    __tablename__ = "chat_conversation"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    title: str = "Neues Gespräch"
    created_at: datetime = ts_field()
    updated_at: datetime = ts_field()


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_message"
    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="chat_conversation.id", index=True, ondelete="CASCADE")
    user_id: int = user_fk()
    role: str  # user|assistant
    content: str = text_field()
    meta: dict[str, Any] = json_field()  # tool calls, pending actions, provider
    created_at: datetime = ts_field()


class PendingAction(SQLModel, table=True):
    __tablename__ = "pending_action"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    conversation_id: int | None = Field(default=None, foreign_key="chat_conversation.id", ondelete="CASCADE")
    tool: str
    args: dict[str, Any] = json_field()
    summary: str = text_field()
    diff: dict[str, Any] = json_field()
    status: str = "pending"  # pending|confirmed|rejected|failed
    result: dict[str, Any] = json_field()
    created_at: datetime = ts_field()
    resolved_at: datetime | None = ts_field(default_now=False)


class CoachHint(SQLModel, table=True):
    __tablename__ = "coach_hint"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    kind: str  # plateau|protein_low|missed_training|new_pr|deload|briefing|checkin|weekly
    title: str
    body: str = text_field()
    data: dict[str, Any] = json_field()
    dedupe_key: str | None = Field(default=None, index=True)
    created_at: datetime = ts_field(index=True)
    read_at: datetime | None = ts_field(default_now=False)
    dismissed: bool = False


class AIUsage(SQLModel, table=True):
    __tablename__ = "ai_usage"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, foreign_key="user.id", index=True, ondelete="CASCADE")
    task: str = "chat"
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0
    duration_ms: int = 0
    success: bool = True
    error: str | None = None
    content: dict[str, Any] | None = json_field(lambda: None, nullable=True)
    created_at: datetime = ts_field(index=True)


class UserAIKey(SQLModel, table=True):
    __tablename__ = "user_ai_key"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    provider: str
    key_enc: str
    created_at: datetime = ts_field()


class PromptTemplate(SQLModel, table=True):
    __tablename__ = "prompt_template"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    version: int = 1
    content: str = text_field()
    comment: str = ""
    is_active: bool = False
    created_by: int | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
    created_at: datetime = ts_field()


class MealPlan(SQLModel, table=True):
    __tablename__ = "meal_plan"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    week_start: date = Field(index=True)
    plan: dict[str, Any] = json_field()  # {"days":[{"day":"Mo","meals":[…]}]}
    shopping_list: list[dict[str, Any]] = json_field(list)
    created_at: datetime = ts_field()
