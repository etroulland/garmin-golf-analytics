"""Machine-readable output and the club-to-club comparison across two windows."""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

import pytest

from garmin_golf_analytics import output
from garmin_golf_analytics.compare_report import (
    club_compare,
    club_profile,
    main,
    player_records,
)

PARS = {"1": 4, "2": 4, "3": 3, "4": 4, "5": 5, "6": 4, "7": 3, "8": 4, "9": 4}
DRIVER = ("Driver", 101)


def shot(meters: float, club_name: str = "Driver", club_id: int = 101,
         shot_type: str = "TEE", start_lie: str = "TeeBox", end_lie: str = "Fairway") -> dict:
    """One tracked shot shaped like garmin_golf_fetch.py writes them."""
    return {
        "clubId": club_id,
        "clubName": club_name,
        "meters": meters,
        "shotType": shot_type,
        "shotOrder": 1,
        "startLoc": {"lie": start_lie},
        "endLoc": {"lie": end_lie},
    }


def round_bundle(played_on: str, driver_meters: list[float],
                 iron_meters: list[float] | None = None) -> dict:
    """A 9-hole round with tracked tee shots, enough for a club comparison."""
    holes = [{"number": index, "strokes": 5, "penalties": 0} for index in range(1, 10)]
    shots: dict = {}
    for index in range(len(driver_meters)):
        shots[str(index + 1)] = [shot(driver_meters[index])]
    if iron_meters:
        for index in range(len(iron_meters)):
            shots.setdefault(str(index + 1), []).append(
                shot(iron_meters[index], club_name="7 Iron", club_id=107,
                     shot_type="APPROACH", start_lie="Fairway", end_lie="Green"))
    return {
        "scorecard": {
            "startTime": f"{played_on}T09:00:00.0",
            "strokes": 45,
            "holes": holes,
            "excludeFromStats": False,
            "sensorOnPutter": False,
        },
        "course": {"pars": PARS},
        "shots": shots,
    }


# --- output formats -------------------------------------------------------

def test_json_keeps_missing_values_as_null():
    """A missing measurement and a measured zero are different facts."""
    buffer = io.StringIO()
    output.write([{"metric": "putts", "a": None, "b": 0}], "json", buffer)
    rows = json.loads(buffer.getvalue())
    assert rows[0]["a"] is None
    assert rows[0]["b"] == 0


def test_json_rounds_floats():
    buffer = io.StringIO()
    output.write([{"x": 1.23456789}], "json", buffer)
    assert json.loads(buffer.getvalue())[0]["x"] == 1.2346


def test_csv_writes_a_header_and_one_line_per_record():
    buffer = io.StringIO()
    output.write([{"club": "Driver", "n": 3}, {"club": "5 Iron", "n": 4}], "csv", buffer)
    rows = list(csv.DictReader(io.StringIO(buffer.getvalue())))
    assert [row["club"] for row in rows] == ["Driver", "5 Iron"]
    assert rows[1]["n"] == "4"


def test_csv_of_nothing_writes_nothing():
    buffer = io.StringIO()
    output.write([], "csv", buffer)
    assert buffer.getvalue() == ""


def test_unknown_format_raises():
    with pytest.raises(ValueError, match="unknown format"):
        output.write([{"a": 1}], "xml", io.StringIO())


# --- per-club profile -----------------------------------------------------

def test_club_profile_reports_one_row_per_club():
    records = club_profile([round_bundle("2026-05-01", [180, 200, 190])], min_meters=0)
    driver = [record for record in records if record["club"] == "Driver"]
    assert len(driver) == 1
    assert driver[0]["n"] == 3
    assert driver[0]["median_m"] == pytest.approx(190)


def test_club_profile_drops_the_club_s_own_mishits():
    """A 20 m driver is a top, not a driver distance: it must not enter the median."""
    records = club_profile([round_bundle("2026-05-01", [20, 180, 190, 200])], min_meters=0)
    driver = next(record for record in records if record["club"] == "Driver")
    assert driver["mishits"] == 1
    assert driver["n"] == 3
    assert driver["median_m"] == pytest.approx(190)


# --- club comparison ------------------------------------------------------

def compare_two(records_and_lines):
    records, lines = records_and_lines
    return records, lines


def test_club_compare_signs_the_delta_from_a_to_b():
    bundles = [round_bundle("2025-05-01", [170, 172, 174]),
               round_bundle("2026-05-01", [190, 192, 194])]
    records, lines = club_compare(bundles,
                                  ((date(2025, 1, 1), date(2025, 12, 31)),
                                   (date(2026, 1, 1), date(2026, 12, 31))),
                                  min_holes=9, min_meters=0, min_shots=3)
    driver = next(record for record in records if record["club"] == "Driver")
    assert driver["median_a_m"] == pytest.approx(172)
    assert driver["median_b_m"] == pytest.approx(192)
    assert driver["delta_m"] == pytest.approx(20)
    assert driver["low_confidence"] is False
    assert any("+20.0" in line for line in lines)


def test_club_compare_withholds_a_delta_on_a_thin_sample():
    """Two shots a side is not an improvement, whatever the numbers say."""
    bundles = [round_bundle("2025-05-01", [170, 172]),
               round_bundle("2026-05-01", [190, 194])]
    records, lines = club_compare(bundles,
                                  ((date(2025, 1, 1), date(2025, 12, 31)),
                                   (date(2026, 1, 1), date(2026, 12, 31))),
                                  min_holes=9, min_meters=0, min_shots=5)
    driver = next(record for record in records if record["club"] == "Driver")
    assert driver["delta_m"] is None
    assert driver["low_confidence"] is True
    assert any("low n" in line for line in lines)


def test_club_compare_keeps_a_club_hit_in_only_one_window():
    """A new club in the bag is the change being looked for: it must not vanish."""
    bundles = [round_bundle("2025-05-01", [170, 172, 174]),
               round_bundle("2026-05-01", [190, 192, 194], iron_meters=[120, 125, 130])]
    records, _ = club_compare(bundles,
                              ((date(2025, 1, 1), date(2025, 12, 31)),
                               (date(2026, 1, 1), date(2026, 12, 31))),
                              min_holes=9, min_meters=0, min_shots=3)
    iron = [record for record in records if record["club"] == "7 Iron"]
    assert iron and iron[0]["n_a"] == 0 and iron[0]["n_b"] == 3
    assert iron[0]["delta_m"] is None


def test_club_compare_of_rounds_with_no_tracked_shot():
    bundles = [round_bundle("2025-05-01", []), round_bundle("2026-05-01", [])]
    records, lines = club_compare(bundles,
                                  ((date(2025, 1, 1), date(2025, 12, 31)),
                                   (date(2026, 1, 1), date(2026, 12, 31))),
                                  min_holes=9, min_meters=0, min_shots=3)
    assert records == []
    assert len(lines) == 2  # the two window reports survive, no table


# --- player records -------------------------------------------------------

def test_player_records_carry_the_same_figures_as_the_table():
    bundles = [round_bundle("2025-05-01", [170]), round_bundle("2026-05-01", [190])]
    records = player_records(bundles,
                            ((date(2025, 1, 1), date(2025, 12, 31)),
                             (date(2026, 1, 1), date(2026, 12, 31))),
                            min_holes=9, min_sample=1)
    by_metric = {record["metric"]: record for record in records}
    assert by_metric["rounds"]["a"] == 1
    assert by_metric["rounds"]["b"] == 1
    assert by_metric["strokes_per_hole"]["delta"] == pytest.approx(0)
    assert by_metric["rounds"]["period_a"] == "2025-01-01..2025-12-31"


def test_player_records_are_none_when_a_window_is_empty():
    bundles = [round_bundle("2026-05-01", [190])]
    assert player_records(bundles,
                          ((date(2025, 1, 1), date(2025, 12, 31)),
                           (date(2026, 1, 1), date(2026, 12, 31))),
                          min_holes=9) is None


def test_player_records_withhold_a_delta_on_a_thin_sample():
    bundles = [round_bundle("2025-05-01", [170]), round_bundle("2026-05-01", [190])]
    records = player_records(bundles,
                             ((date(2025, 1, 1), date(2025, 12, 31)),
                              (date(2026, 1, 1), date(2026, 12, 31))),
                             min_holes=9, min_sample=5)
    by_metric = {record["metric"]: record for record in records}
    assert by_metric["strokes_per_hole"]["delta"] is None
    assert by_metric["strokes_per_hole"]["low_confidence"] is True
    # The two sides are still reported: withheld delta, not withheld data.
    assert by_metric["strokes_per_hole"]["a"] is not None


# --- command line ---------------------------------------------------------

def write_rounds(directory: Path, bundles: list[dict]) -> None:
    for index, bundle in enumerate(bundles):
        played_on = bundle["scorecard"]["startTime"][:10]
        (directory / f"round_{played_on}_{index}.json").write_text(json.dumps(bundle), encoding="utf-8")


def test_main_by_club_prints_a_distance_table(tmp_path, capsys):
    write_rounds(tmp_path, [round_bundle("2025-05-01", [170, 172, 174]),
                            round_bundle("2026-05-01", [190, 192, 194])])
    code = main([str(tmp_path), "--period", "2025", "--period", "2026", "--by", "club"])
    assert code == 0
    assert "Driver" in capsys.readouterr().out


def test_main_by_club_json_is_pure_json(tmp_path, capsys):
    write_rounds(tmp_path, [round_bundle("2025-05-01", [170, 172, 174]),
                            round_bundle("2026-05-01", [190, 192, 194])])
    code = main([str(tmp_path), "--period", "2025", "--period", "2026",
                 "--by", "club", "--format", "json"])
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["club"] == "Driver"


def test_main_player_json_is_pure_json(tmp_path, capsys):
    write_rounds(tmp_path, [round_bundle("2025-05-01", [170]), round_bundle("2026-05-01", [190])])
    code = main([str(tmp_path), "--period", "2025", "--period", "2026", "--format", "json"])
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["metric"] for row in rows} >= {"rounds", "strokes_per_hole"}


def test_main_by_club_without_tracked_shots_exits_one(tmp_path, capsys):
    write_rounds(tmp_path, [round_bundle("2025-05-01", []), round_bundle("2026-05-01", [])])
    code = main([str(tmp_path), "--period", "2025", "--period", "2026", "--by", "club"])
    assert code == 1
    assert "no tracked shot" in capsys.readouterr().err
