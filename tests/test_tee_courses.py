"""Tee accuracy (gga-tee) and the per-course breakdown (gga-courses)."""
from __future__ import annotations

import json

import pytest

from garmin_golf_analytics import course_report, tee_report

PARS = {"1": 4, "2": 4, "3": 3, "4": 4, "5": 5, "6": 4, "7": 3, "8": 4, "9": 4}


def tee_shot(club: str, meters: float = 180.0, order: int = 1) -> dict:
    return {"clubId": 101, "clubName": club, "meters": meters, "shotType": "TEE",
            "shotOrder": order, "startLoc": {"lie": "TeeBox"}, "endLoc": {"lie": "Fairway"}}


def bundle(played_on: str, course: str, outcomes: list[str | None],
           clubs: list[str] | None = None, strokes: int = 5) -> dict:
    """Nine holes, one tee shot per hole, one fairway outcome per hole."""
    holes = []
    for index, outcome in enumerate(outcomes, start=1):
        hole = {"number": index, "strokes": strokes, "penalties": 0}
        if outcome:
            hole["fairwayShotOutcome"] = outcome
        holes.append(hole)
    shots = {}
    for index in range(len(outcomes)):
        club = clubs[index] if clubs else "Driver"
        shots[str(index + 1)] = [tee_shot(club)]
    return {
        "scorecard": {"startTime": f"{played_on}T09:00:00.0", "strokes": strokes * 9,
                      "holes": holes, "excludeFromStats": False, "sensorOnPutter": False},
        "course": {"name": course, "pars": PARS},
        "shots": shots,
    }


# --- tee accuracy ---------------------------------------------------------

def test_a_club_counts_hits_misses_and_unknowns_separately():
    outcomes = ["HIT", "HIT", "LEFT", "RIGHT", None, "HIT", "HIT", "HIT", "HIT"]
    records = tee_report.tee_profile([bundle("2026-05-01", "A", outcomes)])
    driver = records[0]
    assert driver["club"] == "Driver"
    assert (driver["hit"], driver["left"], driver["right"], driver["unknown"]) == (6, 1, 1, 1)
    assert driver["recorded"] == 8
    # 6 of 8 recorded, not 6 of 9: an empty outcome is not a miss.
    assert driver["in_play_percent"] == pytest.approx(75.0)


def test_a_club_with_no_recorded_outcome_has_no_percentage():
    records = tee_report.tee_profile([bundle("2026-05-01", "A", [None] * 9)])
    assert records[0]["in_play_percent"] is None
    assert records[0]["tee_shots"] == 9


def test_each_club_gets_its_own_row():
    outcomes = ["HIT"] * 9
    clubs = ["Driver"] * 5 + ["6 Iron"] * 4
    records = tee_report.tee_profile([bundle("2026-05-01", "A", outcomes, clubs)])
    by_club = {record["club"]: record for record in records}
    assert by_club["Driver"]["tee_shots"] == 5
    assert by_club["6 Iron"]["tee_shots"] == 4


def test_only_the_first_tee_shot_of_a_hole_counts():
    """Two shots tagged TEE on one hole is one drive and its follow-up."""
    item = bundle("2026-05-01", "A", ["HIT"] + [None] * 8)
    item["shots"]["1"] = [tee_shot("Driver", order=1), tee_shot("Driver", order=2)]
    records = tee_report.tee_profile([item])
    assert records[0]["tee_shots"] == 9


def test_a_shot_on_another_hole_is_not_counted_twice():
    item = bundle("2026-05-01", "A", ["RIGHT"] + [None] * 8)
    item["shots"]["1"] = [tee_shot("Driver", order=1), tee_shot("6 Iron", order=2)]
    records = tee_report.tee_profile([item])
    assert [record["club"] for record in records] == ["Driver"]


def test_an_unrecorded_outcome_is_unknown_even_when_the_field_is_present_but_wrong():
    item = bundle("2026-05-01", "A", [None] * 9)
    item["scorecard"]["holes"][0]["fairwayShotOutcome"] = "SOMETHING_NEW"
    records = tee_report.tee_profile([item])
    assert records[0]["unknown"] == 9


def test_tee_report_flags_a_thin_sample():
    records = tee_report.tee_profile([bundle("2026-05-01", "A", ["HIT"] * 4 + [None] * 5,
                                             ["6 Iron"] * 4 + ["Driver"] * 5)])
    lines = tee_report.report(records, min_shots=5)
    assert any("low n" in line for line in lines)


def test_tee_main_prints_a_table(tmp_path, capsys):
    (tmp_path / "round_2026-05-01_0.json").write_text(
        json.dumps(bundle("2026-05-01", "A", ["HIT"] * 9)), encoding="utf-8")
    assert tee_report.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Driver" in out and "100.0%" in out


def test_tee_main_json_is_pure_json(tmp_path, capsys):
    (tmp_path / "round_2026-05-01_0.json").write_text(
        json.dumps(bundle("2026-05-01", "A", ["HIT", "LEFT"] + [None] * 7)), encoding="utf-8")
    assert tee_report.main([str(tmp_path), "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["in_play_percent"] == pytest.approx(50.0)


def test_tee_main_without_tee_shots_exits_one(tmp_path, capsys):
    item = bundle("2026-05-01", "A", ["HIT"] * 9)
    item["shots"] = {}
    (tmp_path / "round_2026-05-01_0.json").write_text(json.dumps(item), encoding="utf-8")
    assert tee_report.main([str(tmp_path)]) == 1
    assert "no tee shot" in capsys.readouterr().err


def test_tee_main_rejects_a_missing_directory(tmp_path, capsys):
    assert tee_report.main([str(tmp_path / "nope")]) == 2
    assert "no such directory" in capsys.readouterr().err


# --- per course -----------------------------------------------------------

def test_courses_keeps_one_row_per_course():
    bundles = [bundle("2026-05-01", "A", ["HIT"] * 9),
               bundle("2026-05-02", "A", ["HIT"] * 9),
               bundle("2026-05-03", "B", ["HIT"] * 9)]
    records = course_report.course_records(bundles)
    by_course = {record["course"]: record for record in records}
    assert by_course["A"]["rounds"] == 2 and by_course["A"]["holes"] == 18
    assert by_course["B"]["rounds"] == 1


def test_courses_keeps_the_hard_average_not_the_mean_of_rounds():
    """Two courses of different lengths must not be compared on raw totals."""
    bundles = [bundle("2026-05-01", "A", ["HIT"] * 9, strokes=5),
               bundle("2026-05-02", "A", ["HIT"] * 9, strokes=6)]
    record = course_report.course_records(bundles)[0]
    assert record["strokes_per_hole"] == pytest.approx(5.5)
    assert record["holes"] == 18


def test_courses_sorts_by_number_of_rounds():
    bundles = [bundle("2026-05-01", "B", ["HIT"] * 9),
               bundle("2026-05-02", "A", ["HIT"] * 9),
               bundle("2026-05-03", "A", ["HIT"] * 9)]
    assert [record["course"] for record in course_report.course_records(bundles)] == ["A", "B"]


def test_a_bundle_without_a_course_name_stays_in_the_report():
    item = bundle("2026-05-01", "", ["HIT"] * 9)
    item["course"] = {}
    records = course_report.course_records([item])
    assert records[0]["course"] == "Unknown course"
    assert records[0]["rounds"] == 1


def test_courses_counts_blowups_per_hole():
    bundles = [bundle("2026-05-01", "A", ["HIT"] * 9, strokes=7)]
    record = course_report.course_records(bundles)[0]
    assert record["blowup_percent"] == pytest.approx(100.0)


def test_courses_putts_only_count_measured_rounds():
    measured = bundle("2026-05-01", "A", ["HIT"] * 9)
    for index, hole in enumerate(measured["scorecard"]["holes"]):
        hole["putts"] = [1, 2, 3, 2, 2, 1, 2, 2, 2][index]
    unmeasured = bundle("2026-05-02", "A", ["HIT"] * 9)
    for hole in unmeasured["scorecard"]["holes"]:
        hole["putts"] = 2
    record = course_report.course_records([measured, unmeasured])[0]
    assert record["putts_measured_rounds"] == 1
    assert record["putts_per_hole"] == pytest.approx(round(sum([1, 2, 3, 2, 2, 1, 2, 2, 2]) / 9, 2))


def test_courses_main_marks_a_course_played_once(tmp_path, capsys):
    (tmp_path / "round_2026-05-01_0.json").write_text(
        json.dumps(bundle("2026-05-01", "A", ["HIT"] * 9)), encoding="utf-8")
    assert course_report.main([str(tmp_path)]) == 0
    assert "one round" in capsys.readouterr().out


def test_courses_main_json_is_pure_json(tmp_path, capsys):
    (tmp_path / "round_2026-05-01_0.json").write_text(
        json.dumps(bundle("2026-05-01", "A", ["HIT"] * 9)), encoding="utf-8")
    assert course_report.main([str(tmp_path), "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["course"] == "A"
