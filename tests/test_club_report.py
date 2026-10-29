"""club_report.py: distance tables, and the same round selection as round_report."""
from __future__ import annotations

import pytest

import garmin_golf_analytics.club_report as club_report
from conftest import bundle, hole, shot


def test_percentile_interpolates():
    values = [10.0, 20.0, 30.0, 40.0]
    assert club_report.percentile(values, 0.5) == pytest.approx(25.0)
    assert club_report.percentile(values, 0.0) == pytest.approx(10.0)
    assert club_report.percentile(values, 1.0) == pytest.approx(40.0)


def test_percentile_of_empty_raises():
    with pytest.raises(ValueError):
        club_report.percentile([], 0.5)


def test_percentile_single_value():
    assert club_report.percentile([7.0], 0.9) == pytest.approx(7.0)


def test_collect_groups_by_club_and_lie():
    shots = [shot("Driver", 200, "TeeBox"), shot("Driver", 220, "TeeBox"),
             shot("Driver", 120, "Rough")]
    grouped = club_report.collect(shots, min_meters=0, lie=None)
    assert grouped[("Driver", "TeeBox")] == [(200.0, "Unknown"), (220.0, "Unknown")]
    assert grouped[("Driver", "Rough")] == [(120.0, "Unknown")]


def test_collect_drops_club_id_zero():
    shots = [{"clubId": 0, "clubName": None, "meters": 150, "startLoc": {"lie": "Rough"}}]
    assert club_report.collect(shots, min_meters=0, lie=None) == {}


def test_collect_drops_excluded_shots():
    shots = []
    flagged = shot("Driver", 200, "TeeBox")
    flagged["excludeFromStats"] = True
    shots.append(flagged)
    assert club_report.collect(shots, min_meters=0, lie=None) == {}


def test_collect_applies_distance_floor():
    shots = [shot("Gap Wedge", 30), shot("Gap Wedge", 80)]
    grouped = club_report.collect(shots, min_meters=40, lie=None)
    assert grouped[("Gap Wedge", "Fairway")] == [(80.0, "Unknown")]


def test_collect_filters_by_lie():
    shots = [shot("Driver", 200, "TeeBox"), shot("Driver", 150, "Fairway")]
    grouped = club_report.collect(shots, min_meters=0, lie="Fairway")
    assert list(grouped) == [("Driver", "Fairway")]


def test_collect_drops_unnamed_clubs():
    # An id in a club table is noise: nothing can be compared to "clubId:100".
    unnamed = shot(None, 150)
    grouped = club_report.collect([unnamed], min_meters=0, lie=None)
    assert grouped == {}


def test_default_min_meters_is_no_floor():
    assert club_report.DEFAULT_MIN_METERS == 0


def test_no_floor_keeps_the_wedges():
    wedge = shot("Sand Wedge", 12)
    grouped = club_report.collect([wedge], min_meters=club_report.DEFAULT_MIN_METERS, lie=None)
    assert ("Sand Wedge", "Fairway") in grouped


def test_collect_ignores_shots_without_meters():
    broken = shot("Driver", 0)
    broken["meters"] = None
    assert club_report.collect([broken], min_meters=0, lie=None) == {}


def test_collect_unknown_lie_label():
    odd = shot("Driver", 150)
    odd["startLoc"] = {}
    grouped = club_report.collect([odd], min_meters=0, lie=None)
    assert ("Driver", "Unknown") in grouped


def test_iter_shots_flattens_holes():
    data = bundle(shots={"1": [shot("Driver", 200, "TeeBox")], "2": [shot("7 Iron", 120)]})
    assert len(list(club_report.iter_shots([data]))) == 2


def test_main_ignores_rounds_garmin_excluded(rounds_dir, capsys):
    """The distance table must ignore a round Garmin excluded, like the score table does."""
    kept = bundle(date="2026-09-01", shots={"1": [shot("Driver", 200, "TeeBox", order=1)]})
    excluded = bundle(date="2026-09-02", exclude=True,
                      shots={"1": [shot("Driver", 100, "TeeBox", order=1)]})
    directory = rounds_dir(kept, excluded)
    assert club_report.main([directory]) == 0
    out = capsys.readouterr().out
    assert "1 excluded by Garmin" in out
    assert "200" in out
    assert "100" not in out


def test_main_keep_excluded_flag_includes_them(rounds_dir, capsys):
    kept = bundle(date="2026-09-01")
    excluded = bundle(date="2026-09-02", exclude=True,
                      shots={"1": [shot("Driver", 100, "TeeBox", order=1)]})
    directory = rounds_dir(kept, excluded)
    assert club_report.main([directory, "--keep-excluded"]) == 0
    out = capsys.readouterr().out
    assert "excluded by Garmin" not in out
    assert "100" in out


def test_main_missing_directory(rounds_dir, capsys, tmp_path):
    assert club_report.main([str(tmp_path / "nope")]) == 2
    assert "no such directory" in capsys.readouterr().err


def test_main_empty_directory(tmp_path, capsys):
    assert club_report.main([str(tmp_path)]) == 1
    assert "no round_*.json" in capsys.readouterr().err


def test_main_flags_low_sample_size(rounds_dir, capsys):
    data = bundle(shots={"1": [shot("7 Iron", 120, "TeeBox", order=1)]})
    assert club_report.main([rounds_dir(data)]) == 0
    assert "(low n)" in capsys.readouterr().out


def test_main_prints_total_distance_label(rounds_dir, capsys):
    data = bundle(shots={"1": [shot("Driver", 200, "TeeBox", order=1)]})
    assert club_report.main([rounds_dir(data)]) == 0
    out = capsys.readouterr().out
    assert "total (GPS, roll included)" in out
    assert "carry" not in out.lower()


def test_report_prints_one_block_per_lie(rounds_dir, capsys):
    data = bundle(shots={"1": [shot("Driver", 200, "TeeBox", order=1),
                               shot("7 Iron", 150, "Fairway", order=2)]})
    assert club_report.main([rounds_dir(data)]) == 0
    out = capsys.readouterr().out
    assert "## TeeBox" in out
    assert "## Fairway" in out
    assert out.index("## TeeBox") < out.index("## Fairway")


def test_lie_order_puts_bunker_and_recovery_last():
    lies = ["Recovery", "Bunker", "Rough", "Fairway", "TeeBox"]
    ordered = sorted(lies, key=lambda n: (club_report.LIE_ORDER.index(n) if n in club_report.LIE_ORDER else 99, n))
    assert ordered[:2] == ["TeeBox", "Fairway"]
    assert ordered[-1] == "Recovery"


def test_collect_drops_putts_on_the_green():
    on_green = shot("Putter", 4, lie="Green")
    on_green["shotType"] = "PUTT"
    on_green["endLoc"] = {"lie": "Green"}
    grouped = club_report.collect([on_green], min_meters=0, lie=None)
    assert grouped == {}


def test_collect_keeps_a_putt_played_off_the_green():
    # Dry, fast turf: the putter is a legitimate approach club.
    approach = shot("Putter", 22, lie="Rough")
    approach["shotType"] = "PUTT"
    approach["endLoc"] = {"lie": "Green"}
    grouped = club_report.collect([approach], min_meters=0, lie=None)
    assert grouped[("Putter (approach)", "Rough")] == [(22.0, "Green")]


def test_collect_keeps_an_untagged_putter_approach():
    approach = shot("Putter", 18, lie="Fairway")
    approach["endLoc"] = {"lie": "Green"}
    grouped = club_report.collect([approach], min_meters=0, lie=None)
    assert ("Putter (approach)", "Fairway") in grouped


def test_collect_drops_a_putter_shot_that_stays_off_the_green():
    miss = shot("Putter", 15, lie="Rough")
    miss["endLoc"] = {"lie": "Rough"}
    grouped = club_report.collect([miss], min_meters=0, lie=None)
    assert grouped == {}


def test_collect_keeps_the_ending_lie():
    landed = shot("Driver", 200)
    landed["endLoc"] = {"lie": "Rough"}
    grouped = club_report.collect([landed], min_meters=0, lie=None)
    assert grouped[("Driver", "Fairway")] == [(200.0, "Rough")]


def test_report_excludes_mishits_from_the_median(rounds_dir, capsys):
    data = bundle(shots={
        "1": [shot("Driver", 200, order=1), shot("Driver", 210, order=2),
              shot("Driver", 25, order=3), shot("Driver", 30, order=4)],
    })
    assert club_report.main([rounds_dir(data), "--min-meters", "0"]) == 0
    out = capsys.readouterr().out
    assert "  2 " in out.split("Driver")[1].split("\n")[0]
    assert "mishits" in out


def test_report_counts_good_lies(rounds_dir, capsys):
    fairway = shot("Driver", 200, order=1)
    fairway["endLoc"] = {"lie": "Fairway"}
    rough = shot("Driver", 190, order=2)
    rough["endLoc"] = {"lie": "Rough"}
    data = bundle(shots={"1": [fairway], "2": [rough]})
    assert club_report.main([rounds_dir(data), "--min-meters", "0"]) == 0
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("Driver")][0]
    assert " 50%" in line
