"""The shot-kind matrix: same table as --matrix, columns are what the shot was.

It answers the question the lie matrix raises but cannot settle: a 6-iron at
158 m off the tee and 121 m off the fairway is two different jobs, and the row
has to say so instead of averaging them into a distance nobody plays.
"""
from __future__ import annotations

from garmin_golf_analytics.club_report import main

ROUND = (
    '{"scorecard": {"startTime": "2026-09-01 08:00:00", "courseGlobalId": 1, "strokes": 40,'
    ' "holes": [{"number": 1, "strokes": 4, "putts": 2, "penalties": 0}]},'
    ' "course": {"pars": {"1": 4}},'
    ' "shots": {"1": ['
    '  {"clubId": 1, "clubName": "6 Iron", "meters": 158.0, "shotOrder": 1, "shotType": "TEE",'
    '   "startLoc": {"lie": "TeeBox"}, "endLoc": {"lie": "Fairway"}},'
    '  {"clubId": 1, "clubName": "6 Iron", "meters": 121.0, "shotOrder": 2, "shotType": "APPROACH",'
    '   "startLoc": {"lie": "Fairway"}, "endLoc": {"lie": "Green"}}'
    ' ]}, "playedHoles": 1}'
)


def run(tmp_path, capsys, *args):
    (tmp_path / "round_2026-09-01_1.json").write_text(ROUND, encoding="utf-8")
    code = main([str(tmp_path), "--min-holes", "1", *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_kind_matrix_splits_one_club_into_its_two_jobs(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys, "--matrix", "Tee,Approach", "--matrix-axis", "kind")
    assert code == 0
    assert "Tee" in out and "Approach" in out
    assert "158 (1)*" in out
    assert "121 (1)*" in out


def test_kind_matrix_default_columns_are_tee_approach_chip(tmp_path, capsys):
    code, out, _ = run(tmp_path, capsys, "--matrix", "--matrix-axis", "kind")
    assert code == 0
    header = next(line for line in out.splitlines() if line.startswith("club"))
    assert header.split() == ["club", "Tee", "Approach", "Chip"]


def test_kind_matrix_refuses_an_unknown_kind(tmp_path, capsys):
    code, _, err = run(tmp_path, capsys, "--matrix", "Drive", "--matrix-axis", "kind")
    assert code == 2
    assert "unknown kind" in err
    assert "Approach" in err, "the refusal must list what is accepted"


def test_kind_matrix_refuses_a_lie_name_used_as_a_kind(tmp_path, capsys):
    """Passing Fairway with --matrix-axis kind is a typo, not an empty table."""
    code, _, err = run(tmp_path, capsys, "--matrix", "Fairway", "--matrix-axis", "kind")
    assert code == 2
    assert "unknown kind" in err


def test_kind_matrix_reports_when_nothing_matches(tmp_path, capsys):
    code, _, err = run(tmp_path, capsys, "--matrix", "Pitch", "--matrix-axis", "kind")
    assert code == 1
    assert "no shot of that kind" in err


def test_lie_matrix_still_validates_lie_names(tmp_path, capsys):
    code, _, err = run(tmp_path, capsys, "--matrix", "Tee", "--matrix-axis", "lie")
    assert code == 2, "Tee is a shot kind, not a lie: TeeBox is the lie"
    assert "unknown lie" in err
