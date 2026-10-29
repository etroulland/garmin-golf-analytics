"""--min-holes: 9 by default, adjustable on every report.

The floor decides which rounds count, so it has to be a real knob and not a
decorative flag: each test changes it and checks the figures move.
"""
from __future__ import annotations

import json

import pytest

from garmin_golf_analytics import club_report, compare_report, round_report
from garmin_golf_analytics.rounds_common import MIN_STROKES_9, short_reason

PARS = {"1": 4, "2": 4, "3": 3, "4": 4, "5": 5, "6": 4, "7": 3, "8": 4, "9": 4}


def bundle(played_on: str, hole_count: int, strokes: int = 5) -> dict:
    # The practice floor in rounds_common is absolute (MIN_STROKES_9 = 35), so a
    # short round has to be scored like one: 5 strokes a hole over 5 holes is 25
    # strokes and would be dropped for looking like a range session.
    if hole_count < 18:
        strokes = max(strokes, -(-MIN_STROKES_9 // hole_count))
    holes = [{"number": index, "strokes": strokes, "penalties": 0}
             for index in range(1, hole_count + 1)]
    return {
        "scorecard": {
            "startTime": f"{played_on}T09:00:00.0",
            "strokes": strokes * hole_count,
            "holes": holes,
            "excludeFromStats": False,
            "sensorOnPutter": False,
        },
        "course": {"pars": PARS},
        "shots": {"1": [{"clubId": 101, "clubName": "Driver", "meters": 180.0,
                         "shotType": "TEE", "shotOrder": 1,
                         "startLoc": {"lie": "TeeBox"}, "endLoc": {"lie": "Fairway"}}]},
    }


def write(tmp_path, bundles) -> str:
    for index, item in enumerate(bundles):
        day = item["scorecard"]["startTime"][:10]
        (tmp_path / f"round_{day}_{index}.json").write_text(json.dumps(item), encoding="utf-8")
    return str(tmp_path)


# --- the default ----------------------------------------------------------

def test_every_report_defaults_min_holes_to_nine():
    for module in (round_report, club_report, compare_report):
        option = module.main.__globals__  # the parser lives inside main(); read the constant
        assert option["DEFAULT_MIN_HOLES"] == 9


def test_a_nine_hole_round_is_kept_and_an_eight_hole_one_is_not():
    assert short_reason(bundle("2026-05-01", 9), 9) is None
    assert short_reason(bundle("2026-05-01", 8), 9) == "partial"


# --- lowering the floor ---------------------------------------------------

def test_rounds_below_the_floor_appear_when_it_is_lowered(tmp_path, capsys):
    directory = write(tmp_path, [bundle("2026-05-01", 9), bundle("2026-05-02", 5)])

    assert round_report.main([directory, "--format", "json"]) == 0
    strict = json.loads(capsys.readouterr().out)
    assert len(strict) == 1

    assert round_report.main([directory, "--format", "json", "--min-holes", "5"]) == 0
    loose = json.loads(capsys.readouterr().out)
    assert len(loose) == 2
    assert {row["holes"] for row in loose} == {5, 9}


def test_the_hole_count_is_what_moves_not_the_round_count(tmp_path, capsys):
    """A 5-hole round has 5 holes, not 9: the pad must not inflate the sample."""
    directory = write(tmp_path, [bundle("2026-05-01", 9), bundle("2026-05-02", 5)])

    assert round_report.main([directory, "--format", "json", "--min-holes", "5"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert sorted(row["holes"] for row in rows) == [5, 9]


# --- raising it -----------------------------------------------------------

def test_raising_the_floor_drops_a_nine_hole_round(tmp_path, capsys):
    directory = write(tmp_path, [bundle("2026-05-01", 9), bundle("2026-05-02", 18)])

    assert round_report.main([directory, "--format", "json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 2

    assert round_report.main([directory, "--format", "json", "--min-holes", "18"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["holes"] for row in rows] == [18]


# --- propagation to the other two reports ---------------------------------

def test_clubs_follows_the_same_knob(tmp_path, capsys):
    directory = write(tmp_path, [bundle("2026-05-01", 5)])

    assert club_report.main([directory, "--format", "json"]) == 1
    assert "no shot above the distance floor" in capsys.readouterr().err

    assert club_report.main([directory, "--format", "json", "--min-holes", "5"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["club"] == "Driver"


def test_compare_follows_the_same_knob(tmp_path, capsys):
    directory = write(tmp_path, [bundle("2025-05-01", 5), bundle("2026-05-01", 5)])
    periods = ["--period", "2025", "--period", "2026"]

    assert compare_report.main([directory, *periods, "--format", "json"]) == 1
    assert "nothing to compare" in capsys.readouterr().err

    assert compare_report.main([directory, *periods, "--format", "json", "--min-holes", "5"]) == 0
    rows = json.loads(capsys.readouterr().out)
    by_metric = {row["metric"]: row for row in rows}
    assert by_metric["rounds"]["a"] == 1
    assert by_metric["rounds"]["b"] == 1


def test_compare_by_club_follows_the_same_knob(tmp_path, capsys):
    directory = write(tmp_path, [bundle("2025-05-01", 5), bundle("2026-05-01", 5)])
    periods = ["--period", "2025", "--period", "2026", "--by", "club"]

    assert compare_report.main([directory, *periods, "--format", "json"]) == 1

    assert compare_report.main([directory, *periods, "--format", "json",
                                "--min-holes", "5"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["n_a"] == 1 and rows[0]["n_b"] == 1


def test_min_holes_rejects_something_that_is_not_a_number(tmp_path):
    directory = write(tmp_path, [bundle("2026-05-01", 9)])
    with pytest.raises(SystemExit) as raised:
        round_report.main([directory, "--min-holes", "nine"])
    assert raised.value.code == 2
