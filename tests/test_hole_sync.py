"""hole_sync.py: the reports must admit what the watch never recorded."""
from __future__ import annotations

from conftest import bundle, hole, shot
from garmin_golf_analytics.hole_sync import coverage, hole_discrepancy, hole_shots, non_putt_count


def test_hole_shots_normalises_keys_to_int():
    data = {"shots": {"1": [shot("Driver", 200)], "12": []}}
    assert sorted(hole_shots(data)) == [1, 12]


def test_hole_shots_handles_missing_key():
    assert hole_shots({}) == {}


def test_non_putt_count_ignores_tracked_putts():
    shots = [shot("Driver", 200), {"shotType": "PUTT", "meters": 3},
             {"shotType": "PUTT", "meters": 1}]
    assert non_putt_count(shots) == 1


def test_discrepancy_zero_when_everything_lines_up():
    played = hole(1, 4, putts=2)
    shots = [shot("Driver", 200), shot("7 Iron", 100)]
    assert hole_discrepancy(played, shots) == 0


def test_discrepancy_positive_when_shots_are_missing():
    played = hole(1, 7, putts=2)
    shots = [shot("Driver", 200)]
    assert hole_discrepancy(played, shots) == 4


def test_discrepancy_negative_when_more_shots_than_strokes():
    played = hole(1, 3, putts=1)
    shots = [shot("Driver", 200), shot("7 Iron", 100), shot("Putter", 2)]
    assert hole_discrepancy(played, shots) == -1


def test_discrepancy_ignores_tracked_putts_in_the_count():
    # A tracked PUTT is already inside `putts`: counting it twice would hide a gap.
    played = hole(1, 4, putts=2)
    shots = [shot("Driver", 200), shot("7 Iron", 100), {"shotType": "PUTT", "meters": 3}]
    assert hole_discrepancy(played, shots) == 0


def test_coverage_counts_holes_off_and_missing_strokes():
    holes = [hole(1, 4, putts=2), hole(2, 5, putts=2), hole(3, None)]
    data = bundle(holes=holes, shots={
        "1": [shot("Driver", 200), shot("7 Iron", 100)],
        "2": [shot("Driver", 190)],
        "3": [],
    })
    total, off, missing = coverage(data)
    assert total == 2
    assert off == 1
    assert missing == 2


def test_coverage_of_a_fully_tracked_round():
    holes = [hole(n, 3, putts=1) for n in range(1, 10)]
    data = bundle(holes=holes, shots={"%d" % n: [shot("5 Iron", 150), shot("8 Iron", 90)]
                                      for n in range(1, 10)})
    assert coverage(data) == (9, 0, 0)


def test_coverage_never_crashes_on_empty_scorecard():
    assert coverage({"scorecard": {"holes": []}}) == (0, 0, 0)
