"""The club x lie matrix: one table, clubs in rows, lies in columns.

The question it answers is the one asked on the course: does this club still
travel the same distance off the rough as off the fairway?
"""
from __future__ import annotations

from garmin_golf_analytics.club_report import main, report_matrix


def collect(*triples):
    """Build the (club, lie) -> [(distance, end lie)] mapping report_matrix reads."""
    out: dict[tuple, list[tuple[float, str]]] = {}
    for club, lie, meters in triples:
        out.setdefault((club, lie), []).append((float(meters), "Fairway"))
    return out


def test_matrix_prints_a_median_per_club_and_lie(capsys):
    grouped = collect(("7 Iron", "TeeBox", 170), ("7 Iron", "TeeBox", 174), ("7 Iron", "Rough", 106))
    report_matrix(grouped, min_shots=5, lies=("TeeBox", "Fairway"))
    out = capsys.readouterr().out
    assert "TeeBox" in out and "Fairway" in out
    assert "170 (2)*" in out.replace("174", "170") or "172 (2)*" in out
    assert "106" not in out, "a lie outside the requested columns must not appear"


def test_matrix_marks_an_empty_cell_with_a_dash(capsys):
    report_matrix(collect(("Driver", "TeeBox", 195)), min_shots=5, lies=("TeeBox", "Fairway"))
    out = capsys.readouterr().out
    driver_line = [line for line in out.splitlines() if line.startswith("Driver")][0]
    assert "-" in driver_line.split("TeeBox")[-1] or driver_line.rstrip().endswith("-")


def test_matrix_flags_cells_below_the_sample_threshold(capsys):
    report_matrix(collect(("8 Iron", "TeeBox", 133)), min_shots=5, lies=("TeeBox",))
    out = capsys.readouterr().out
    assert "133 (1)*" in out
    assert "fewer than 5" in out


def test_matrix_orders_clubs_by_the_first_column(capsys):
    grouped = collect(("Driver", "TeeBox", 240), ("7 Iron", "TeeBox", 170),
                      ("8 Iron", "TeeBox", 130))
    report_matrix(grouped, min_shots=5, lies=("TeeBox", "Fairway"))
    import re
    out = capsys.readouterr().out
    order = re.findall(r"^(Driver|7 Iron|8 Iron)\s+(\d+)", out, re.MULTILINE)
    assert order == [("Driver", "240"), ("7 Iron", "170"), ("8 Iron", "130")]


def test_matrix_reports_empty_input_on_stderr(capsys):
    report_matrix({("Driver", "Bunker"): [(30.0, "Green")]}, min_shots=5, lies=("TeeBox",))
    captured = capsys.readouterr()
    assert "no shot in those lies" in captured.err


def test_cli_matrix_rejects_an_unknown_lie(tmp_path, capsys):
    (tmp_path / "round_2026-09-01_1.json").write_text(
        '{"scorecard": {"startTime": "2026-09-01 08:00:00", "courseGlobalId": 1, "strokes": 40,'
        ' "holes": [{"number": 1, "strokes": 4, "putts": 2, "penalties": 0}]},'
        ' "shots": {"1": []}, "playedHoles": 1}', encoding="utf-8")
    assert main([str(tmp_path), "--min-holes", "1", "--matrix", "Foo"]) == 2
    assert "unknown lie" in capsys.readouterr().err


def test_cli_matrix_defaults_to_teebox_and_fairway(tmp_path, capsys):
    (tmp_path / "round_2026-09-01_1.json").write_text(
        '{"scorecard": {"startTime": "2026-09-01 08:00:00", "courseGlobalId": 1, "strokes": 40,'
        ' "holes": [{"number": 1, "strokes": 4, "putts": 2, "penalties": 0}]},'
        ' "course": {"pars": {"1": 4}},'
        ' "shots": {"1": [{"clubId": 1, "clubName": "7 Iron", "meters": 150.0, "shotOrder": 1,'
        ' "shotType": "TEE", "startLoc": {"lie": "TeeBox"}, "endLoc": {"lie": "Fairway"}}]},'
        ' "playedHoles": 1}', encoding="utf-8")
    assert main([str(tmp_path), "--min-holes", "1", "--matrix"]) == 0
    out = capsys.readouterr().out
    assert "TeeBox" in out and "Fairway" in out
    assert "150 (1)*" in out
