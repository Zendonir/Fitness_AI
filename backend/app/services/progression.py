"""Progressive Overload: Double Progression mit konfigurierbarer Regel pro Übung."""

from dataclasses import dataclass, field
from typing import Any

DEFAULT_RULE = {"rep_min": 8, "rep_max": 12, "increment_kg": 2.5, "all_sets": True, "max_rpe": 9.5}


def epley(weight: float, reps: int) -> float:
    """Geschätztes 1RM nach Epley."""
    if reps <= 0 or weight <= 0:
        return 0.0
    if reps == 1:
        return float(weight)
    return round(weight * (1 + reps / 30), 2)


def round_to(value: float, step: float) -> float:
    if step <= 0:
        return round(value, 2)
    return round(round(value / step) * step, 2)


@dataclass
class SetData:
    reps: int
    weight_kg: float
    rpe: float | None = None
    is_warmup: bool = False


@dataclass
class Suggestion:
    weight_kg: float | None
    reps: int
    sets: int
    action: str  # start|increase|add_reps|hold|deload
    reason: str
    last: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def merge_rule(exercise_rule: dict[str, Any] | None, rep_min: int | None = None, rep_max: int | None = None) -> dict[str, Any]:
    rule = {**DEFAULT_RULE, **(exercise_rule or {})}
    if rep_min:
        rule["rep_min"] = rep_min
    if rep_max:
        rule["rep_max"] = rep_max
    if rule["rep_min"] > rule["rep_max"]:
        rule["rep_min"], rule["rep_max"] = rule["rep_max"], rule["rep_min"]
    return rule


def suggest(
    history: list[list[SetData]],
    rule: dict[str, Any],
    target_sets: int = 3,
    deload: bool = False,
    deload_factor: float = 0.6,
) -> Suggestion:
    """history: Arbeitssätze der letzten Einheiten, neueste zuerst."""
    rmin, rmax, inc = int(rule["rep_min"]), int(rule["rep_max"]), float(rule["increment_kg"])
    sessions = [[s for s in sess if not s.is_warmup and s.reps > 0] for sess in history]
    sessions = [s for s in sessions if s]
    if not sessions:
        return Suggestion(None, rmin, target_sets, "start", "Noch keine Daten – starte mit einem Gewicht, "
                          f"das du sauber für {rmax} Wdh. schaffst.")
    last = sessions[0]
    last_dump = [{"reps": s.reps, "weight_kg": s.weight_kg, "rpe": s.rpe} for s in last]
    top_weight = max(s.weight_kg for s in last)
    top_sets = [s for s in last if s.weight_kg == top_weight]

    if deload:
        return Suggestion(
            round_to(top_weight * 0.9, inc), rmin, max(1, round(target_sets * deload_factor)), "deload",
            "Deload-Woche: weniger Sätze und ca. 90 % des Gewichts – Erholung für den nächsten Block.", last_dump,
        )

    reached = [s.reps >= rmax for s in top_sets]
    too_hard = any(s.rpe is not None and s.rpe > rule.get("max_rpe", 9.5) for s in top_sets)
    done = all(reached) if rule.get("all_sets", True) else any(reached)
    if done and not too_hard:
        return Suggestion(
            round_to(top_weight + inc, inc) if top_weight > 0 else top_weight, rmin, target_sets, "increase",
            f"Obere Grenze von {rmax} Wdh. erreicht → +{inc:g} kg und wieder bei {rmin} Wdh. starten.", last_dump,
        )

    # Zweimal in Folge klar unter dem Wiederholungsbereich -> Gewicht reduzieren
    def failed(sess: list[SetData]) -> bool:
        tw = max(s.weight_kg for s in sess)
        tops = [s for s in sess if s.weight_kg == tw]
        return sum(s.reps < rmin for s in tops) > len(tops) / 2

    if len(sessions) >= 2 and failed(sessions[0]) and failed(sessions[1]) and top_weight > 0:
        return Suggestion(
            round_to(top_weight * 0.9, inc), rmin, target_sets, "deload",
            f"Zweimal unter {rmin} Wdh. – Gewicht um 10 % reduzieren und neu aufbauen.", last_dump,
        )

    min_reps = min(s.reps for s in top_sets)
    target_reps = min(max(min_reps + 1, rmin), rmax)
    return Suggestion(
        top_weight, target_reps, target_sets, "add_reps" if target_reps > min_reps else "hold",
        f"Gleiches Gewicht, Ziel {target_reps} Wdh. pro Satz (Bereich {rmin}–{rmax}).", last_dump,
    )
