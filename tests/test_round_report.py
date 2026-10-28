"""round_report.py: the aggregate, the drop reasons, and the putt labelling."""
from __future__ import annotations

import round_report
from conftest import bundle, hole


def nine(putts=2, strokes=5, penalties=0):
    return [hole(n, strokes, putts=putts, penalties=penalties) for n in range(1, 10)]


def test_report_drops_excluded_round(rounds_dir, capsys):
    data = rounds_dir(bundle(), bundle(date="2026-09-02", exclude=True))
    assert round_report.main([data]) == 0
    captured = capsys.readouterr()
    assert "1 rounds kept" in captured.out
    assert "1 excluded by Garmin" in captured.out
    assert "excluded by Garmin: 2026-09-02" in captured.err


def test_report_drops_partial_and_practice(rounds_dir, capsys):
    data = rounds_dir(
        bundle(date="2026-09-01"),
        bundle(date="2026-09-02", holes=[hole(n, 4) for n in range(1, 6)]),
        bundle(date="2026-09-03", holes=nine(strokes=2), strokes=18),
    )
    assert round_report.main([data]) == 0
    out = capsys.readouterr().out
    assert "1 partial" in out
    assert "1 practice" in out


def test_report_prints_one_line_per_kept_round(rounds_dir, capsys):
    data = rounds_dir(bundle(date="2026-09-01"), bundle(date="2026-09-02", course=25555))
    assert round_report.main([data]) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if "holes=" in l]
    assert len(lines) == 2
    assert "2026-09-01" in lines[0]


def test_report_never_labels_constant_putts_as_data(rounds_dir, capsys):
    data = rounds_dir(bundle(holes=nine(putts=2)))
    assert round_report.main([data]) == 0
    out = capsys.readouterr().out
    assert "no putt data" in out
    assert "putts: unavailable" in out


def test_report_aggregates_manual_putts(rounds_dir, capsys):
    holes = [hole(n, 5, putts=p) for n, p in enumerate([1, 2, 2, 3, 2, 2, 1, 2, 2], start=1)]
    data = rounds_dir(bundle(holes=holes))
    assert round_report.main([data]) == 0
    out = capsys.readouterr().out
    assert "manual entry, sensor off" in out
    assert "3-putt rate 11%" in out


def test_report_blowup_count_and_penalties(rounds_dir, capsys):
    holes = [hole(1, 9), hole(2, 8), hole(3, 4, penalties=2)] + [hole(n, 5) for n in range(4, 10)]
    data = rounds_dir(bundle(holes=holes))
    assert round_report.main([data]) == 0
    out = capsys.readouterr().out
    assert "blow-up holes (>=7 strokes): 2/9 = 22%" in out
    assert "penalties: 2 over 1 rounds" in out
    assert "distribution:" in out


def test_report_median_and_mean(rounds_dir, capsys):
    holes = [hole(n, s) for n, s in enumerate([4, 4, 4, 4, 4, 5, 5, 5, 5], start=1)]
    data = rounds_dir(bundle(holes=holes, strokes=40))
    assert round_report.main([data]) == 0
    out = capsys.readouterr().out
    assert "median 4.0" in out
    assert "mean 4.44" in out


def test_report_min_holes_override(rounds_dir, capsys):
    data = rounds_dir(bundle(holes=[hole(n, 6) for n in range(1, 7)], strokes=36))
    assert round_report.main([data, "--min-holes", "6"]) == 0
    assert "1 rounds kept" in capsys.readouterr().out


def test_report_missing_directory(tmp_path, capsys):
    assert round_report.main([str(tmp_path / "nope")]) == 2
    assert "no such directory" in capsys.readouterr().err


def test_report_empty_directory(tmp_path, capsys):
    assert round_report.main([str(tmp_path)]) == 1
    assert "no round_*.json" in capsys.readouterr().err


def test_report_nothing_to_aggregate(rounds_dir, capsys):
    data = rounds_dir(bundle(holes=[hole(n, 5) for n in range(1, 10)]))
    assert round_report.main([data, "--min-holes", "18"]) == 0
    out = capsys.readouterr().out
    assert "0 rounds kept" in out
    assert "nothing to aggregate" in out


def test_report_keep_excluded(rounds_dir, capsys):
    data = rounds_dir(bundle(exclude=True))
    assert round_report.main([data, "--keep-excluded"]) == 0
    assert "1 rounds kept" in capsys.readouterr().out


def test_report_prints_to_par_when_course_pars_exist(rounds_dir, capsys):
    data = bundle(holes=[hole(n, 5) for n in range(1, 10)], strokes=45)
    data["course"] = {"pars": {str(i): 4 for i in range(1, 10)}}
    assert round_report.main([rounds_dir(data)]) == 0
    out = capsys.readouterr().out
    assert "par=36" in out
    assert "to_par=+9" in out
    assert "to par: median +9" in out


def test_report_says_so_when_pars_are_missing(rounds_dir, capsys):
    data = rounds_dir(bundle())
    assert round_report.main([data]) == 0
    assert "to par: unavailable" in capsys.readouterr().out
