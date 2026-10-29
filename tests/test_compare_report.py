"""Period parsing, per-hole normalisation and the two-window comparison."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from garmin_golf_analytics.compare_report import (
    compare,
    entry_point,
    in_period,
    main,
    parse_period,
    profile,
)

PARS = {"1": 4, "2": 4, "3": 3, "4": 4, "5": 5, "6": 4, "7": 3, "8": 4, "9": 4}


def round_bundle(played_on: str, strokes: list[int], putts: list[int] | None = None,
                 pars: dict | None = None, handicap: int = 0) -> dict:
    """One bundle shaped like garmin_golf_fetch.py writes them."""
    pars = PARS if pars is None else pars
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
            "sensorOnPutter": False,
            "handicappedStrokes": handicap,
        },
        "course": {"pars": pars},
        "shots": {},
    }


# --- period parsing -------------------------------------------------------

def test_parse_explicit_dates():
    assert parse_period("2025-04-01:2025-10-31") == (date(2025, 4, 1), date(2025, 10, 31))


def test_parse_whole_year():
    assert parse_period("2025") == (date(2025, 1, 1), date(2025, 12, 31))


def test_parse_rejects_reversed_dates():
    with pytest.raises(ValueError, match="after"):
        parse_period("2026-02-01:2026-01-01")


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_period("last summer")


def test_in_period_includes_both_ends():
    bundle = round_bundle("2026-06-30", [4] * 9)
    assert in_period(bundle, (date(2026, 1, 1), date(2026, 6, 30)))
    assert not in_period(bundle, (date(2026, 1, 1), date(2026, 6, 29)))


# --- per-hole normalisation ----------------------------------------------

def test_profile_reports_per_hole_not_per_round():
    """A 9-hole and an 18-hole round must not skew strokes per hole."""
    nine = round_bundle("2026-01-01", [6] * 9)
    eighteen = round_bundle("2026-02-01", [5] * 9, pars=PARS)
    result = profile([nine, eighteen])
    assert result["rounds"] == 2
    assert result["holes"] == 18


def test_profile_over_par_is_per_hole():
    # par 35 over these 9 holes, 41 strokes: +6 over 9 holes, not +6 per hole.
    bundle = round_bundle("2026-01-01", [4, 4, 3, 5, 6, 5, 4, 5, 5])
    result = profile([bundle])
    assert result["to_par_per_hole"] == pytest.approx(6 / 9)


def test_profile_counts_blowups_and_penalties():
    bundle = round_bundle("2026-01-01", [4, 4, 3, 4, 5, 4, 3, 4, 7])
    result = profile([bundle])
    assert result["blowup_rate"] == pytest.approx(100 / 9)
    assert result["penalties_per_round"] == 0


def test_profile_drops_constant_putt_fill():
    """Garmin fills 2 putts on every hole when the sensor is off: not data."""
    bundle = round_bundle("2026-01-01", [5] * 9, putts=[2] * 9)
    assert profile([bundle])["putt_rate_3"] is None


def test_profile_uses_putts_when_varied():
    bundle = round_bundle("2026-01-01", [5] * 9, putts=[2, 2, 3, 2, 2, 2, 3, 2, 2])
    result = profile([bundle])
    assert result["putt_rate_3"] == pytest.approx(200 / 9)


def test_profile_without_par_has_no_over_par():
    bundle = round_bundle("2026-01-01", [5] * 9, pars={})
    assert profile([bundle])["to_par_per_hole"] is None


def test_profile_of_nothing():
    assert profile([]) == {"rounds": 0, "holes": 0}


# --- the comparison itself -----------------------------------------------

def test_compare_prints_a_signed_delta(capsys):
    before = [round_bundle("2025-05-01", [6] * 9, handicap=2)]
    after = [round_bundle("2026-05-01", [5] * 9, handicap=2)]
    code = compare(before + after,
                   ((date(2025, 1, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 12, 31))),
                   min_holes=9)
    out = capsys.readouterr().out
    assert code == 0
    # 6 -> 5 strokes per hole is a delta of -1.00, signed from the first window.
    assert "-1.00" in out
    assert "strokes per hole" in out


def test_compare_flags_a_thin_sample(capsys):
    before = [round_bundle("2025-05-01", [6] * 9)]
    after = [round_bundle("2026-05-01", [5] * 9)]
    compare(before + after,
            ((date(2025, 1, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 12, 31))),
            min_holes=9, min_sample=5)
    assert "Low confidence" in capsys.readouterr().out


def test_compare_fails_when_one_window_is_empty(capsys):
    bundles = [round_bundle("2026-05-01", [5] * 9)]
    code = compare(bundles,
                   ((date(2025, 1, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 12, 31))),
                   min_holes=9)
    assert code == 1
    assert "nothing to compare" in capsys.readouterr().err


def test_compare_excludes_short_rounds(capsys):
    """A 3-hole round must not enter a window: same rules as the other reports."""
    bundles = [round_bundle("2025-05-01", [4, 4, 4])]
    code = compare(bundles,
                   ((date(2025, 1, 1), date(2025, 12, 31)), (date(2025, 6, 1), date(2025, 12, 31))),
                   min_holes=9)
    assert code == 1


# --- command line ---------------------------------------------------------

def write_rounds(directory: Path, bundles: list[dict]) -> None:
    for index, bundle in enumerate(bundles):
        played_on = bundle["scorecard"]["startTime"][:10]
        (directory / f"round_{played_on}_{index}.json").write_text(json.dumps(bundle), encoding="utf-8")


def test_main_compares_two_directories(tmp_path, capsys):
    write_rounds(tmp_path, [round_bundle("2025-05-01", [6] * 9), round_bundle("2026-05-01", [5] * 9)])
    code = main([str(tmp_path), "--period", "2025", "--period", "2026"])
    assert code == 0
    assert "strokes per hole" in capsys.readouterr().out


def test_main_rejects_a_missing_directory(tmp_path, capsys):
    assert main([str(tmp_path / "nope"), "--period", "2025", "--period", "2026"]) == 2
    assert "no such directory" in capsys.readouterr().err


def test_main_rejects_a_bad_period(tmp_path, capsys):
    write_rounds(tmp_path, [round_bundle("2026-05-01", [5] * 9)])
    assert main([str(tmp_path), "--period", "nope", "--period", "2026"]) == 2
    assert "expected START:END" in capsys.readouterr().err


def test_main_rejects_three_periods(tmp_path, capsys):
    write_rounds(tmp_path, [round_bundle("2026-05-01", [5] * 9)])
    assert main([str(tmp_path), "--period", "2025", "--period", "2026", "--period", "2026"]) == 2
    assert "two --period values" in capsys.readouterr().err


def test_main_reports_an_empty_directory(tmp_path, capsys):
    assert main([str(tmp_path), "--period", "2025", "--period", "2026"]) == 1
    assert "no round_*.json" in capsys.readouterr().err


def test_entry_point_swallows_a_closed_pipe(monkeypatch):
    def boom(argv=None):
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr("garmin_golf_analytics.compare_report.main", boom)
    assert entry_point([]) == 0


def test_entry_point_propagates_real_errors(monkeypatch):
    def boom(argv=None):
        raise RuntimeError("not a pipe")

    monkeypatch.setattr("garmin_golf_analytics.compare_report.main", boom)
    with pytest.raises(RuntimeError):
        entry_point([])
