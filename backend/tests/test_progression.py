from app.services.progression import SetData, epley, merge_rule, round_to, suggest

RULE = merge_rule({"rep_min": 8, "rep_max": 12, "increment_kg": 2.5})


def s(reps, w, rpe=None):
    return SetData(reps, w, rpe)


def test_epley():
    assert epley(100, 1) == 100
    assert epley(100, 10) == 133.33
    assert epley(0, 5) == 0


def test_round_to():
    assert round_to(81.3, 2.5) == 82.5
    assert round_to(81.2, 1.25) == 81.25


def test_no_history_starts():
    r = suggest([], RULE)
    assert r.action == "start" and r.weight_kg is None and r.reps == 8


def test_increase_when_all_sets_hit_top():
    r = suggest([[s(12, 60), s(12, 60), s(12, 60)]], RULE)
    assert r.action == "increase" and r.weight_kg == 62.5 and r.reps == 8


def test_hold_weight_add_reps():
    r = suggest([[s(12, 60), s(10, 60), s(9, 60)]], RULE)
    assert r.action == "add_reps" and r.weight_kg == 60 and r.reps == 10


def test_any_set_mode():
    rule = merge_rule({"rep_min": 8, "rep_max": 12, "increment_kg": 2.5, "all_sets": False})
    r = suggest([[s(12, 60), s(10, 60)]], rule)
    assert r.action == "increase"


def test_rpe_too_high_blocks_increase():
    r = suggest([[s(12, 60, 10), s(12, 60, 10)]], RULE)
    assert r.action != "increase"


def test_warmups_ignored():
    r = suggest([[SetData(12, 20, None, True), s(12, 60), s(12, 60)]], RULE)
    assert r.weight_kg == 62.5


def test_two_failures_deload():
    r = suggest([[s(5, 80), s(4, 80)], [s(6, 80), s(5, 80)]], RULE)
    assert r.action == "deload" and r.weight_kg == 72.5


def test_deload_week():
    r = suggest([[s(10, 100)]], RULE, target_sets=4, deload=True, deload_factor=0.5)
    assert r.action == "deload" and r.sets == 2 and r.weight_kg == 90


def test_plan_rep_range_overrides():
    rule = merge_rule({"rep_min": 8, "rep_max": 12}, 4, 6)
    r = suggest([[s(6, 100), s(6, 100)]], rule)
    assert r.action == "increase" and r.reps == 4
