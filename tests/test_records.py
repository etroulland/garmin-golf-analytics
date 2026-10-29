"""The per-round and per-club machine-readable records behind --format."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from garmin_golf_analytics.club_report import club_records, split_mishits
from garmin_golf_analytics.round_report import main as rounds_main, round_records

PARS = {"1": 4, "2": 4, "3": 3, "4": 4, "5": 5, "6": 4, "7": 3, "8": 4, "9": 4}


def bundle(played_on: str, strokes: list[int], putts: list[int] | None = None,
           shots: dict | None = None, sensor: bool = False) -> dict:
    holes = []
    for index, value in enumerate(strokes, start=1):
        hole = {"number": index, "strokes": value, "penalties": 0}
        if putts is not None:
            hole["putts"] = putts[index - 1]
        holes.append(hole)
    return {
        "scorecard": {
            "startTime": f"{played_on}T09:00:00.0",
            "strokes": sum(strokes),
            "holes": holes,
            "excludeFromStats": False,
            "sensorOnPutter": sensor,
            "handicappedStrokes": 0,
        },
        "course": {"pars": PARS},
        "shots": shots or {},
    }


def tee_shot(meters: float) -> dict:
    return {"clubId": 101, "clubName": "Driver", "meters": meters, "shotType": "TEE",
            "shotOrder": 1, "startLoc": {"lie": "TeeBox"}, "endLoc": {"lie": "Fairway"}}


# --- per-round records ----------------------------------------------------

def test_round_records_carry_one_line_per_kept_round():
    records = round_records([bundle("2026-05-01", [5] * 9), bundle("2026-06-01", [4] * 9)], min_holes=9)
    assert [record["played_on"] for record in records] == ["2026-05-01", "2026-06-01"]
    assert records[0]["to_par"] == pytest.approx(45 - 35)


def test_round_records_drop_the_rounds_the_table_drops():
    short = bundle("2026-05-01", [4, 4, 4])
    assert round_records([short], min_holes=9) == []


def test_round_records_leave_putts_null_without_data():
    """A constant fill of 2 is Garmin's default, not a measurement."""
    records = round_records([bundle("2026-05-01", [5] * 9, putts=[2] * 9)], min_holes=9)
    assert records[0]["putts"] is None
    assert records[0]["putt_source"].startswith("no putt data")


def test_round_records_keep_varied_putts():
    values = [2, 2, 3, 2, 2, 2, 3, 2, 2]
    records = round_records([bundle("2026-05-01", [5] * 9, putts=values)], min_holes=9)
    assert records[0]["putts"] == sum(values)


def test_rounds_main_json_is_pure_json(tmp_path, capsys):
    (tmp_path / "round_2026-05-01_0.json").write_text(json.dumps(bundle("2026-05-01", [5] * 9)),
                                                      encoding="utf-8")
    assert rounds_main([str(tmp_path), "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["holes"] == 9


def test_rounds_main_json_without_a_usable_round_exits_one(tmp_path, capsys):
    (tmp_path / "round_2026-05-01_0.json").write_text(json.dumps(bundle("2026-05-01", [3, 3, 3])),
                                                      encoding="utf-8")
    assert rounds_main([str(tmp_path), "--format", "json"]) == 1
    assert "no usable round" in capsys.readouterr().err


# --- per-club records -----------------------------------------------------

def test_split_mishits_uses_the_club_s_own_floor():
    played, mishits = split_mishits([20.0, 100.0, 120.0, 140.0])
    assert mishits == 1
    assert 20.0 not in played


def test_split_mishits_of_nothing():
    assert split_mishits([]) == ([], 0)


def test_club_records_hold_the_same_figures_as_the_table():
    shots = {"1": [tee_shot(180), tee_shot(200)]}
    records = club_records([bundle("2026-05-01", [5] * 9, shots=shots)], min_meters=0)
    driver = [record for record in records if record["club"] == "Driver"][0]
    assert driver["lie"] == "TeeBox"
    assert driver["n"] == 2
    assert driver["median_m"] == pytest.approx(190)
    assert driver["good_lie_percent"] == pytest.approx(100.0)
