"""Vorbefüllte Übungsbibliothek (ca. 80 Übungen)."""

MUSCLES: dict[str, str] = {
    "chest": "Brust",
    "front_delts": "Vordere Schulter",
    "side_delts": "Seitliche Schulter",
    "rear_delts": "Hintere Schulter",
    "biceps": "Bizeps",
    "triceps": "Trizeps",
    "forearms": "Unterarme",
    "abs": "Bauch",
    "obliques": "Seitliche Bauchmuskeln",
    "lats": "Latissimus",
    "traps": "Trapez",
    "upper_back": "Oberer Rücken",
    "lower_back": "Unterer Rücken",
    "glutes": "Gesäß",
    "quads": "Quadrizeps",
    "hamstrings": "Beinbeuger",
    "adductors": "Adduktoren",
    "calves": "Waden",
}

EQUIPMENT = {
    "barbell": "Langhantel",
    "dumbbell": "Kurzhantel",
    "machine": "Maschine",
    "cable": "Kabelzug",
    "bodyweight": "Körpergewicht",
    "kettlebell": "Kettlebell",
    "band": "Widerstandsband",
    "other": "Sonstiges",
}

# (slug, name, category, equipment, primary, secondary, hinweis)
_E = [
    # Brust
    ("bench_press", "Bankdrücken", "compound", "barbell", ["chest"], ["triceps", "front_delts"], "Schulterblätter zurück und unten, Füße fest, Stange zur unteren Brust."),
    ("incline_bench_press", "Schrägbankdrücken", "compound", "barbell", ["chest", "front_delts"], ["triceps"], "Bank 30–45°, Stange zur oberen Brust."),
    ("decline_bench_press", "Negativbankdrücken", "compound", "barbell", ["chest"], ["triceps"], ""),
    ("db_bench_press", "Kurzhantel-Bankdrücken", "compound", "dumbbell", ["chest"], ["triceps", "front_delts"], "Volle Bewegungsamplitude, kontrolliert absenken."),
    ("db_incline_press", "Kurzhantel-Schrägbankdrücken", "compound", "dumbbell", ["chest", "front_delts"], ["triceps"], ""),
    ("db_fly", "Kurzhantel-Fliegende", "isolation", "dumbbell", ["chest"], ["front_delts"], "Leicht gebeugte Ellbogen, Dehnung spüren."),
    ("cable_fly", "Cable Crossover", "isolation", "cable", ["chest"], ["front_delts"], ""),
    ("pec_deck", "Butterfly-Maschine", "isolation", "machine", ["chest"], [], ""),
    ("chest_press_machine", "Brustpresse", "compound", "machine", ["chest"], ["triceps", "front_delts"], ""),
    ("push_up", "Liegestütz", "compound", "bodyweight", ["chest"], ["triceps", "front_delts", "abs"], "Körper bildet eine Linie."),
    ("dips", "Dips", "compound", "bodyweight", ["chest", "triceps"], ["front_delts"], "Leichte Vorlage betont die Brust."),
    # Rücken
    ("deadlift", "Kreuzheben", "compound", "barbell", ["hamstrings", "glutes", "lower_back"], ["traps", "forearms", "quads", "lats"], "Neutraler Rücken, Stange nah am Körper."),
    ("romanian_deadlift", "Rumänisches Kreuzheben", "compound", "barbell", ["hamstrings", "glutes"], ["lower_back"], "Hüfte nach hinten schieben, Knie leicht gebeugt."),
    ("barbell_row", "Langhantelrudern", "compound", "barbell", ["lats", "upper_back"], ["biceps", "rear_delts", "lower_back"], ""),
    ("pendlay_row", "Pendlay Row", "compound", "barbell", ["upper_back", "lats"], ["biceps", "rear_delts"], ""),
    ("db_row", "Einarmiges Kurzhantelrudern", "compound", "dumbbell", ["lats", "upper_back"], ["biceps", "rear_delts"], ""),
    ("pull_up", "Klimmzug", "compound", "bodyweight", ["lats"], ["biceps", "upper_back", "forearms"], "Volle Streckung unten, Brust zur Stange."),
    ("chin_up", "Klimmzug Untergriff", "compound", "bodyweight", ["lats", "biceps"], ["upper_back"], ""),
    ("lat_pulldown", "Latziehen", "compound", "cable", ["lats"], ["biceps", "upper_back"], ""),
    ("close_grip_pulldown", "Latziehen enger Griff", "compound", "cable", ["lats"], ["biceps"], ""),
    ("seated_cable_row", "Rudern am Kabel sitzend", "compound", "cable", ["upper_back", "lats"], ["biceps", "rear_delts"], ""),
    ("machine_row", "Rudermaschine", "compound", "machine", ["upper_back", "lats"], ["biceps"], ""),
    ("t_bar_row", "T-Bar-Rudern", "compound", "barbell", ["upper_back", "lats"], ["biceps", "lower_back"], ""),
    ("straight_arm_pulldown", "Überzüge am Kabel", "isolation", "cable", ["lats"], [], ""),
    ("back_extension", "Rückenstrecker (Hyperextension)", "isolation", "bodyweight", ["lower_back", "glutes"], ["hamstrings"], ""),
    ("shrug", "Shrugs", "isolation", "dumbbell", ["traps"], [], ""),
    ("rack_pull", "Rack Pull", "compound", "barbell", ["upper_back", "traps", "glutes"], ["lower_back", "forearms"], ""),
    # Schultern
    ("overhead_press", "Schulterdrücken stehend", "compound", "barbell", ["front_delts"], ["triceps", "side_delts", "abs"], "Gesäß anspannen, Kopf durch die Arme."),
    ("db_shoulder_press", "Kurzhantel-Schulterdrücken", "compound", "dumbbell", ["front_delts"], ["triceps", "side_delts"], ""),
    ("machine_shoulder_press", "Schulterpresse", "compound", "machine", ["front_delts"], ["triceps"], ""),
    ("arnold_press", "Arnold Press", "compound", "dumbbell", ["front_delts", "side_delts"], ["triceps"], ""),
    ("lateral_raise", "Seitheben", "isolation", "dumbbell", ["side_delts"], ["traps"], "Ellbogen führen, nicht schwingen."),
    ("cable_lateral_raise", "Seitheben am Kabel", "isolation", "cable", ["side_delts"], [], ""),
    ("front_raise", "Frontheben", "isolation", "dumbbell", ["front_delts"], [], ""),
    ("rear_delt_fly", "Reverse Flys", "isolation", "dumbbell", ["rear_delts"], ["upper_back"], ""),
    ("face_pull", "Face Pulls", "isolation", "cable", ["rear_delts", "upper_back"], ["traps"], "Seil zur Stirn, Ellbogen hoch."),
    ("upright_row", "Aufrechtes Rudern", "compound", "barbell", ["side_delts", "traps"], ["biceps"], ""),
    # Arme
    ("barbell_curl", "Langhantel-Curls", "isolation", "barbell", ["biceps"], ["forearms"], ""),
    ("db_curl", "Kurzhantel-Curls", "isolation", "dumbbell", ["biceps"], ["forearms"], ""),
    ("hammer_curl", "Hammer Curls", "isolation", "dumbbell", ["biceps", "forearms"], [], ""),
    ("incline_db_curl", "Schrägbank-Curls", "isolation", "dumbbell", ["biceps"], [], ""),
    ("preacher_curl", "Scottcurls", "isolation", "machine", ["biceps"], [], ""),
    ("cable_curl", "Bizeps-Curls am Kabel", "isolation", "cable", ["biceps"], ["forearms"], ""),
    ("triceps_pushdown", "Trizepsdrücken am Kabel", "isolation", "cable", ["triceps"], [], ""),
    ("overhead_triceps_extension", "Trizeps Überkopfstrecken", "isolation", "cable", ["triceps"], [], ""),
    ("skull_crusher", "French Press (SZ)", "isolation", "barbell", ["triceps"], [], ""),
    ("close_grip_bench", "Enges Bankdrücken", "compound", "barbell", ["triceps", "chest"], ["front_delts"], ""),
    ("db_kickback", "Trizeps-Kickbacks", "isolation", "dumbbell", ["triceps"], [], ""),
    ("wrist_curl", "Handgelenk-Curls", "isolation", "dumbbell", ["forearms"], [], ""),
    # Beine
    ("back_squat", "Kniebeuge", "compound", "barbell", ["quads", "glutes"], ["adductors", "lower_back", "hamstrings"], "Knie über die Zehen, Brust aufrecht, Tiefe mindestens parallel."),
    ("front_squat", "Frontkniebeuge", "compound", "barbell", ["quads"], ["glutes", "abs", "upper_back"], ""),
    ("goblet_squat", "Goblet Squat", "compound", "dumbbell", ["quads", "glutes"], ["abs"], ""),
    ("hack_squat", "Hackenschmidt-Kniebeuge", "compound", "machine", ["quads"], ["glutes"], ""),
    ("leg_press", "Beinpresse", "compound", "machine", ["quads", "glutes"], ["adductors"], ""),
    ("bulgarian_split_squat", "Bulgarische Kniebeuge", "compound", "dumbbell", ["quads", "glutes"], ["adductors", "hamstrings"], ""),
    ("walking_lunge", "Ausfallschritte gehend", "compound", "dumbbell", ["quads", "glutes"], ["hamstrings", "adductors"], ""),
    ("step_up", "Step-ups", "compound", "dumbbell", ["quads", "glutes"], [], ""),
    ("leg_extension", "Beinstrecker", "isolation", "machine", ["quads"], [], ""),
    ("lying_leg_curl", "Beinbeuger liegend", "isolation", "machine", ["hamstrings"], ["calves"], ""),
    ("seated_leg_curl", "Beinbeuger sitzend", "isolation", "machine", ["hamstrings"], [], ""),
    ("nordic_curl", "Nordic Curls", "isolation", "bodyweight", ["hamstrings"], [], ""),
    ("hip_thrust", "Hip Thrust", "compound", "barbell", ["glutes"], ["hamstrings"], "Kinn zur Brust, oben Gesäß maximal anspannen."),
    ("glute_bridge", "Glute Bridge", "isolation", "bodyweight", ["glutes"], ["hamstrings"], ""),
    ("cable_kickback", "Gesäß-Kickbacks am Kabel", "isolation", "cable", ["glutes"], [], ""),
    ("hip_adduction", "Adduktorenmaschine", "isolation", "machine", ["adductors"], [], ""),
    ("hip_abduction", "Abduktorenmaschine", "isolation", "machine", ["glutes"], [], ""),
    ("standing_calf_raise", "Wadenheben stehend", "isolation", "machine", ["calves"], [], "Volle Dehnung unten, kurz halten."),
    ("seated_calf_raise", "Wadenheben sitzend", "isolation", "machine", ["calves"], [], ""),
    ("kb_swing", "Kettlebell Swing", "compound", "kettlebell", ["glutes", "hamstrings"], ["lower_back", "abs"], ""),
    ("good_morning", "Good Mornings", "compound", "barbell", ["hamstrings", "lower_back"], ["glutes"], ""),
    # Rumpf
    ("plank", "Unterarmstütz (Plank)", "isolation", "bodyweight", ["abs"], ["obliques"], ""),
    ("side_plank", "Seitstütz", "isolation", "bodyweight", ["obliques"], ["abs"], ""),
    ("hanging_leg_raise", "Beinheben hängend", "isolation", "bodyweight", ["abs"], ["obliques", "forearms"], ""),
    ("cable_crunch", "Crunches am Kabel", "isolation", "cable", ["abs"], [], ""),
    ("crunch", "Crunches", "isolation", "bodyweight", ["abs"], [], ""),
    ("ab_wheel", "Ab Wheel Rollout", "isolation", "other", ["abs"], ["lats", "obliques"], ""),
    ("russian_twist", "Russian Twist", "isolation", "bodyweight", ["obliques"], ["abs"], ""),
    ("pallof_press", "Pallof Press", "isolation", "cable", ["obliques", "abs"], [], ""),
    ("farmers_walk", "Farmer's Walk", "compound", "dumbbell", ["forearms", "traps"], ["abs", "glutes"], ""),
    # Cardio-Übungen (für Supersätze/Zirkel)
    ("burpee", "Burpees", "cardio", "bodyweight", ["quads", "chest"], ["abs", "triceps"], ""),
    ("jump_rope", "Seilspringen", "cardio", "other", ["calves"], ["quads"], ""),
    ("rowing_machine", "Rudergerät", "cardio", "machine", ["upper_back", "quads"], ["lats", "biceps", "hamstrings"], ""),
]


def seed_exercises() -> list[dict]:
    out = []
    for slug, name, cat, eq, prim, sec, hint in _E:
        iso = cat == "isolation"
        out.append(
            {
                "slug": slug,
                "name": name,
                "category": cat,
                "equipment": eq,
                "primary_muscles": prim,
                "secondary_muscles": sec,
                "instructions": hint,
                "progression": {
                    "rep_min": 10 if iso else 6,
                    "rep_max": 15 if iso else 10,
                    "increment_kg": 1.0 if iso or eq == "dumbbell" else 2.5,
                    "all_sets": True,
                },
                "visibility": "public",
            }
        )
    return out
