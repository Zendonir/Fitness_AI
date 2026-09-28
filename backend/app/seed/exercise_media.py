"""Zuordnung der Seed-Übungen zu animierten GIFs aus ExerciseGymGifsDB.

Quelle: https://github.com/JahelCuadrado/ExerciseGymGifsDB (über jsDelivr-CDN). Die GIFs gehören ihren jeweiligen
Autoren; FitForge speichert nur die Kennung und lädt die Animation zur Anzeige direkt vom CDN.
"""

MEDIA_VERSION = "v1.2.0"
MEDIA_BASE = f"https://cdn.jsdelivr.net/gh/JahelCuadrado/ExerciseGymGifsDB@{MEDIA_VERSION}"

# FitForge-Slug -> ExerciseGymGifsDB-ID (<muskel>/<slug>)
SEED_MEDIA: dict[str, str] = {
    "bench_press": "pectorals/barbell-bench-press",
    "incline_bench_press": "pectorals/barbell-incline-bench-press",
    "decline_bench_press": "pectorals/barbell-decline-bench-press",
    "db_bench_press": "pectorals/dumbbell-bench-press",
    "db_incline_press": "pectorals/dumbbell-incline-bench-press",
    "db_fly": "pectorals/dumbbell-fly",
    "cable_fly": "pectorals/cable-cross-over-variation",
    "pec_deck": "pectorals/lever-seated-fly",
    "chest_press_machine": "pectorals/lever-chest-press",
    "push_up": "pectorals/push-up",
    "dips": "pectorals/chest-dip",
    "deadlift": "glutes/barbell-deadlift",
    "romanian_deadlift": "glutes/barbell-romanian-deadlift",
    "barbell_row": "upper-back/barbell-bent-over-row",
    "pendlay_row": "upper-back/barbell-pendlay-row",
    "db_row": "upper-back/dumbbell-one-arm-bent-over-row",
    "pull_up": "lats/pull-up",
    "chin_up": "lats/chin-up",
    "lat_pulldown": "lats/cable-lat-pulldown-full-range-of-motion",
    "close_grip_pulldown": "lats/cable-lateral-pulldown-with-v-bar",
    "seated_cable_row": "upper-back/cable-seated-row",
    "machine_row": "upper-back/lever-seated-row",
    "t_bar_row": "upper-back/lever-t-bar-row",
    "straight_arm_pulldown": "lats/cable-straight-arm-pulldown",
    "back_extension": "spine/hyperextension",
    "shrug": "traps/dumbbell-shrug",
    "rack_pull": "glutes/barbell-rack-pull",
    "overhead_press": "delts/barbell-standing-close-grip-military-press",
    "db_shoulder_press": "delts/dumbbell-seated-shoulder-press",
    "machine_shoulder_press": "delts/lever-shoulder-press",
    "arnold_press": "delts/dumbbell-arnold-press",
    "lateral_raise": "delts/dumbbell-lateral-raise",
    "cable_lateral_raise": "delts/cable-lateral-raise",
    "front_raise": "delts/dumbbell-front-raise",
    "rear_delt_fly": "delts/dumbbell-rear-fly",
    "face_pull": "delts/cable-rear-delt-row-with-rope",
    "upright_row": "delts/barbell-upright-row",
    "barbell_curl": "biceps/barbell-curl",
    "db_curl": "biceps/dumbbell-biceps-curl",
    "hammer_curl": "biceps/dumbbell-hammer-curl",
    "incline_db_curl": "biceps/dumbbell-incline-curl",
    "preacher_curl": "biceps/lever-preacher-curl",
    "cable_curl": "biceps/cable-curl",
    "triceps_pushdown": "triceps/cable-pushdown",
    "overhead_triceps_extension": "triceps/cable-kneeling-triceps-extension",
    "skull_crusher": "triceps/barbell-lying-triceps-extension-skull-crusher",
    "close_grip_bench": "triceps/barbell-close-grip-bench-press",
    "db_kickback": "triceps/dumbbell-kickback",
    "wrist_curl": "forearms/barbell-palms-up-wrist-curl-over-a-bench",
    "back_squat": "glutes/barbell-full-squat",
    "front_squat": "glutes/barbell-front-squat",
    "goblet_squat": "quads/dumbbell-goblet-squat",
    "hack_squat": "glutes/sled-hack-squat",
    "leg_press": "glutes/sled-45-leg-press",
    "bulgarian_split_squat": "quads/dumbbell-single-leg-split-squat",
    "walking_lunge": "glutes/walking-lunge",
    "step_up": "glutes/dumbbell-step-up",
    "leg_extension": "quads/lever-leg-extension",
    "lying_leg_curl": "hamstrings/lever-lying-leg-curl",
    "seated_leg_curl": "hamstrings/lever-seated-leg-curl",
    "nordic_curl": "hamstrings/glute-ham-raise",
    "hip_thrust": "glutes/barbell-glute-bridge",
    "glute_bridge": "glutes/low-glute-bridge-on-floor",
    "cable_kickback": "glutes/cable-standing-hip-extension",
    "hip_adduction": "adductors/lever-seated-hip-adduction",
    "hip_abduction": "abductors/lever-seated-hip-abduction",
    "standing_calf_raise": "calves/lever-standing-calf-raise",
    "seated_calf_raise": "calves/lever-seated-calf-raise",
    "kb_swing": "glutes/kettlebell-swing",
    "good_morning": "hamstrings/barbell-good-morning",
    "plank": "abs/weighted-front-plank",
    "side_plank": "abs/bodyweight-incline-side-plank",
    "hanging_leg_raise": "abs/hanging-leg-raise",
    "cable_crunch": "abs/cable-kneeling-crunch",
    "crunch": "abs/crunch-floor",
    "ab_wheel": "abs/wheel-rollerout",
    "russian_twist": "abs/russian-twist",
    "pallof_press": "abs/band-horizontal-pallof-press",
    "farmers_walk": "quads/farmers-walk",
    "burpee": "cardio/burpee",
    "jump_rope": "cardio/jump-rope",
}


def gif_url(media_id: str | None) -> str | None:
    return f"{MEDIA_BASE}/{media_id}.gif" if media_id else None


def thumb_url(media_id: str | None) -> str | None:
    return f"{MEDIA_BASE}/{media_id}.thumb.webp" if media_id else None
