"""Round selection rules: one sample, one set of rules, one reason per drop."""
from __future__ import annotations

import json

import pytest

import garmin_golf_analytics.rounds_common as rounds_common
from conftest import bundle, hole
from garmin_golf_analytics.rounds_common import load_bundles, played_holes, select, short_reason


def test_played_holes_ignores_padded_holes():
    data = bundle(holes=[hole(1, 4), hole(2, None), hole(3, 5)])
    assert len(played_holes(data)) == 2


def test_excluded_round_is_split_out():
    data = bundle(exclude=True)
    selection = select([data], min_holes=9)
    assert selection.kept == []
    assert selection.excluded == [data]


def test_keep_excluded_flag_restores_them():
    data = bundle(exclude=True)
    selection = select([data], min_holes=9, keep_excluded=True)
    assert selection.kept == [data]
    assert selection.excluded == []


def test_partial_round_dropped():
    data = bundle(holes=[hole(n, 5) for n in range(1, 8)])
    assert short_reason(data, min_holes=9) == "partial"
    assert select([data], min_holes=9).partial == [data]


def test_partial_checked_before_stroke_floor():
    # 8 holes under the floor is a partial round, not a practice one.
    data = bundle(holes=[hole(n, 3) for n in range(1, 9)])
    assert short_reason(data, min_holes=9) == "partial"


def test_nine_hole_round_below_floor_is_practice():
    holes = [hole(n, 3) for n in range(1, 10)]
    data = bundle(holes=holes, strokes=27)
    assert short_reason(data, min_holes=9) == "practice"


def test_eighteen_hole_round_uses_its_own_floor():
    holes = [hole(n, 3) for n in range(1, 19)]
    assert short_reason(bundle(holes=holes, strokes=54), min_holes=9) == "practice"
    holes = [hole(n, 3 if n < 18 else 9) for n in range(1, 19)]
    assert short_reason(bundle(holes=holes, strokes=60), min_holes=9) is None


def test_clean_round_is_kept():
    assert short_reason(bundle(), min_holes=9) is None
    assert len(select([bundle()], min_holes=9).kept) == 1


def test_describe_counts_each_reason():
    selection = select(
        [bundle(), bundle(exclude=True), bundle(holes=[hole(1, 4)])],
        min_holes=9,
    )
    text = selection.describe()
    assert "1 rounds kept" in text
    assert "1 excluded by Garmin" in text
    assert "1 partial" in text
    assert "practice" not in text
    assert selection.dropped == 2


def test_describe_omits_empty_reasons():
    assert select([bundle()], min_holes=9).describe() == "1 rounds kept"


def test_missing_strokes_counts_as_zero_not_crash():
    data = bundle(holes=[hole(n, 5) for n in range(1, 10)])
    data["scorecard"]["strokes"] = None
    assert short_reason(data, min_holes=9) == "practice"


def test_select_ignores_unknown_files(tmp_path):
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "round_2026-09-01_1.json").write_text(json.dumps(bundle()))
    assert len(load_bundles(str(tmp_path))) == 1


def test_load_bundles_sorted(tmp_path):
    (tmp_path / "round_2026-09-02_2.json").write_text(json.dumps(bundle(date="2026-09-02")))
    (tmp_path / "round_2026-08-30_1.json").write_text(json.dumps(bundle(date="2026-08-30")))
    names = [b["scorecard"]["startTime"][:10] for b in load_bundles(str(tmp_path))]
    assert names == ["2026-08-30", "2026-09-02"]


def test_stroke_floors_are_module_constants():
    # Guards the thresholds themselves: changing them silently changes every report.
    assert rounds_common.MIN_STROKES_9 == 35
    assert rounds_common.MIN_STROKES_18 == 60


def test_load_bundles_missing_directory_raises():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_bundles("/nonexistent/dir")
