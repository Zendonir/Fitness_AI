from datetime import date, datetime
from typing import Any

from sqlmodel import Field, SQLModel

from app.models.base import json_field, text_field, ts_field, user_fk


class Exercise(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int | None = Field(default=None, foreign_key="user.id", index=True, ondelete="CASCADE")
    slug: str | None = Field(default=None, index=True)
    name: str = Field(index=True)
    category: str = "compound"  # compound|isolation|cardio|mobility
    equipment: str = "barbell"  # barbell|dumbbell|machine|cable|bodyweight|kettlebell|band|other
    primary_muscles: list[str] = json_field(list)
    secondary_muscles: list[str] = json_field(list)
    instructions: str = text_field()
    # Definitionen eigener Satzfelder, z. B. [{"key":"tempo","label":"Tempo","type":"text"}]
    custom_fields: list[dict[str, Any]] = json_field(list)
    # Double-Progression: {"rep_min":8,"rep_max":12,"increment_kg":2.5,"all_sets":true}
    progression: dict[str, Any] = json_field()
    visibility: str = "private"  # private|shared|public
    created_at: datetime = ts_field()


class Plan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int | None = Field(default=None, foreign_key="user.id", index=True, ondelete="CASCADE")
    name: str
    description: str = text_field()
    is_template: bool = False
    weeks: int = 4
    deload_weeks: list[int] = json_field(list)  # 1-basiert
    deload_factor: float = 0.6  # Volumenfaktor in Deload-Wochen
    visibility: str = "private"
    is_active: bool = False
    started_on: date | None = None
    created_at: datetime = ts_field()
    updated_at: datetime = ts_field()


class PlanDay(SQLModel, table=True):
    __tablename__ = "plan_day"
    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="plan.id", index=True, ondelete="CASCADE")
    name: str
    position: int = 0
    weekday: int | None = None  # 0=Mo … 6=So, optional
    notes: str = text_field()


class PlanExercise(SQLModel, table=True):
    __tablename__ = "plan_exercise"
    id: int | None = Field(default=None, primary_key=True)
    plan_day_id: int = Field(foreign_key="plan_day.id", index=True, ondelete="CASCADE")
    exercise_id: int = Field(foreign_key="exercise.id", ondelete="CASCADE")
    position: int = 0
    sets: int = 3
    rep_min: int = 8
    rep_max: int = 12
    target_rpe: float | None = 8.0
    rest_seconds: int = 120
    superset_group: str | None = None
    notes: str = text_field()


class Workout(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    client_id: str | None = Field(default=None, index=True, max_length=64)
    plan_day_id: int | None = Field(default=None, foreign_key="plan_day.id", ondelete="SET NULL")
    name: str = "Training"
    started_at: datetime = ts_field(index=True)
    finished_at: datetime | None = ts_field(default_now=False)
    notes: str = text_field()
    rating: int | None = None  # 1-5 Gefühl
    is_deload: bool = False


class WorkoutSet(SQLModel, table=True):
    __tablename__ = "workout_set"
    id: int | None = Field(default=None, primary_key=True)
    workout_id: int = Field(foreign_key="workout.id", index=True, ondelete="CASCADE")
    user_id: int = user_fk()
    client_id: str | None = Field(default=None, index=True, max_length=64)
    exercise_id: int = Field(foreign_key="exercise.id", index=True, ondelete="CASCADE")
    position: int = 0
    reps: int = 0
    weight_kg: float = 0.0
    rpe: float | None = None
    is_warmup: bool = False
    completed: bool = True
    superset_group: str | None = None
    custom: dict[str, Any] = json_field()
    created_at: datetime = ts_field()


class CardioSession(SQLModel, table=True):
    __tablename__ = "cardio_session"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = user_fk()
    client_id: str | None = Field(default=None, index=True, max_length=64)
    kind: str = "run"  # run|bike|row|walk|swim|other
    started_at: datetime = ts_field(index=True)
    duration_s: int = 0
    distance_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    kcal: float | None = None
    elevation_m: float | None = None
    source: str = "manual"  # manual|gpx|csv|health
    track: list[list[float]] = json_field(list)  # [[lat,lon,ele,sec],…] vereinfacht
    notes: str = text_field()
