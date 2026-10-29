"""gga-spread: the dispersion of each club, not just where its middle sits."""
from __future__ import annotations

import json

import pytest

from garmin_golf_analytics import spread_report

PARS = {"1": 4, "2": 4, "3": 3, "4": 4, "5": 5, "6": 4, "7": 3, "8": 4, "9": 4}


def shot(meters: float, club: str = "Driver", order: int = 1,
         shot_type: str = "TEE") -> dict:
    return {"clubId": 101, "clubName": club, "meters": meters, "shotType": shot_type,
            "shotOrder": order, "startLoc": {"lie": "TeeBox"}, "endLoc": {"lie": "Fairway"}}


def bundle(distances: list[float], club: str = "Driver") -> dict:
    holes = [{"number": index, "strokes": 5, "penalties": 0} for index in range(1, 10)]
    shots = {str(index + 1): [shot(distance, club)]
             for index, distance in enumerate(distances)}
    return {
        "scorecard": {"startTime": "2026-05-01T09:00:00.0", "strokes": 45, "holes": holes,
                      "excludeFromStats": False, "sensorOnPutter": False},
        "course": {"pars": PARS},
        "shots": shots,
    }


def one(distances: list[float], club: str = "Driver") -> dict:
    records = spread_report.spread_profile([bundle(distances, club)])
    return records[0]


# --- dispersion -----------------------------------------------------------

def test_a_tight_club_and_a_wild_one_share_a_median_but_not_a_band():
    """The whole point: the median cannot tell these two apart."""
    tight = one([168.0, 170.0, 170.0, 170.0, 172.0])
    wild = one([140.0, 150.0, 170.0, 190.0, 200.0])
    assert tight["median_m"] == pytest.approx(wild["median_m"] or 170.0)
    assert tight["spread_m"] < wild["spread_m"]
    assert tight["cv_percent"] < wild["cv_percent"]


def test_a_constant_club_has_no_dispersion():
    record = one([170.0] * 6)
    assert record["stdev_m"] == pytest.approx(0.0)
    assert record["cv_percent"] == pytest.approx(0.0)
    assert record["spread_m"] == pytest.approx(0.0)


def test_the_band_is_the_interquartile_range():
    record = one([100.0, 110.0, 120.0, 130.0, 140.0])
    assert record["p25_m"] == pytest.approx(110.0)
    assert record["p75_m"] == pytest.approx(130.0)
    assert record["spread_m"] == pytest.approx(20.0)


def test_short_shots_count_under_eighty_percent_of_the_median():
    # median 100, floor at 80: the 70 is short, the 85 is not.
    record = one([70.0, 95.0, 100.0, 105.0, 130.0])
    assert record["short_m"] == pytest.approx(record["median_m"] * 0.8)
    assert record["short_percent"] > 0


def test_a_club_with_nothing_short_has_zero_short_percent():
    record = one([170.0, 172.0, 174.0, 176.0, 178.0])
    assert record["short_percent"] == pytest.approx(0.0)


def test_mishits_stay_out_of_the_dispersion():
    """A 20 m top is not variance in a 170 m driver: it must not inflate the spread."""
    clean = one([160.0, 170.0, 180.0])
    polluted = one([20.0, 160.0, 170.0, 180.0])
    assert polluted["n"] == clean["n"]
    assert polluted["stdev_m"] == pytest.approx(clean["stdev_m"])


def test_each_shot_kind_gets_its_own_row():
    holes = [{"number": index, "strokes": 5, "penalties": 0} for index in range(1, 10)]
    shots = {"1": [shot(180.0, shot_type="TEE")], "2": [shot(120.0, shot_type="APPROACH")]}
    item = {"scorecard": {"startTime": "2026-05-01T09:00:00.0", "strokes": 45, "holes": holes,
                          "excludeFromStats": False},
            "course": {"pars": PARS}, "shots": shots}
    kinds = {record["shot_kind"] for record in spread_report.spread_profile([item])}
    assert {"Tee", "Approach"} <= kinds


# --- command line ---------------------------------------------------------

def write(tmp_path, item: dict) -> str:
    (tmp_path / "round_2026-05-01_0.json").write_text(json.dumps(item), encoding="utf-8")
    return str(tmp_path)


def test_main_prints_a_table(tmp_path, capsys):
    directory = write(tmp_path, bundle([168.0, 170.0, 172.0]))
    assert spread_report.main([directory]) == 0
    out = capsys.readouterr().out
    assert "Driver" in out and "band" in out


def test_main_json_is_pure_json(tmp_path, capsys):
    directory = write(tmp_path, bundle([168.0, 170.0, 172.0]))
    assert spread_report.main([directory, "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["club"] == "Driver"
    assert rows[0]["spread_m"] is not None


def test_main_flags_a_thin_sample(tmp_path, capsys):
    directory = write(tmp_path, bundle([168.0, 170.0]))
    assert spread_report.main([directory]) == 0
    assert "low n" in capsys.readouterr().out


def test_main_without_tracked_shots_exits_one(tmp_path, capsys):
    item = bundle([170.0])
    item["shots"] = {}
    directory = write(tmp_path, item)
    assert spread_report.main([directory]) == 1
    assert "no tracked shot" in capsys.readouterr().err


def test_main_rejects_a_missing_directory(tmp_path, capsys):
    assert spread_report.main([str(tmp_path / "nope")]) == 2
    assert "no such directory" in capsys.readouterr().err
