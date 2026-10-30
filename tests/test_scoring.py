"""scoring.py: par is joined on the hole number, and scorecard.score is not trusted."""
from __future__ import annotations

from conftest import bundle, hole

from garmin_golf_analytics.scoring import (
    format_relative,
    handicap_strokes,
    hole_pars,
    net_score,
    played_par,
    relative_score,
)

GRAVES = "443454345543435435"  # 18 holes, par 72


def with_course(holes, pars=GRAVES, strokes=None, handicap=0, handicap_strokes=0, **kwargs):
    data = bundle(holes=holes, strokes=strokes, **kwargs)
    data["course"] = {"pars": {str(i): int(c) for i, c in enumerate(pars, start=1)},
                      "roundPar": sum(int(c) for c in pars) if len(pars) == 18 else None}
    data["scorecard"]["playerHandicap"] = handicap
    data["scorecard"]["handicappedStrokes"] = handicap_strokes
    return data


def test_hole_pars_returns_int_keys():
    data = with_course([hole(1, 4)])
    assert hole_pars(data)[1] == 4
    assert hole_pars(data)[18] == 5


def test_hole_pars_empty_without_course_block():
    assert hole_pars(bundle()) == {}


def test_played_par_joins_on_hole_number_not_position():
    # BACK_9: holes[] lists numbers 10..18, pars must come from positions 10..18.
    holes = [hole(n, 5) for n in range(10, 19)]
    data = with_course(holes)
    assert played_par(data) == sum(int(c) for c in GRAVES[9:])


def test_played_par_of_a_full_18():
    holes = [hole(n, 5) for n in range(1, 19)]
    assert played_par(with_course(holes)) == 72


def test_played_par_ignores_unplayed_holes():
    holes = [hole(1, 4), hole(2, None), hole(3, 4)]
    assert played_par(with_course(holes)) == 4 + 3  # pars of holes 1 and 3


def test_played_par_dash_when_a_hole_has_no_par():
    holes = [hole(1, 4), hole(19, 4)]
    assert played_par(with_course(holes)) is None


def evaluated_par(holes):
    return sum(int(GRAVES[h["number"] - 1]) for h in holes)


def test_relative_score_is_strokes_minus_par():
    holes = [hole(n, 5) for n in range(10, 19)]
    data = with_course(holes, strokes=40)
    assert relative_score(data) == 40 - evaluated_par(holes)


def test_relative_score_of_an_even_round():
    holes = [hole(n, int(GRAVES[n - 1])) for n in range(1, 19)]
    data = with_course(holes, strokes=72)
    assert relative_score(data) == 0
    assert format_relative(relative_score(data)) == "E"


def test_relative_score_none_without_pars():
    assert relative_score(bundle(strokes=40)) is None


def test_relative_score_none_without_strokes():
    holes = [hole(1, 4)]
    data = with_course(holes)
    data["scorecard"]["strokes"] = None
    assert relative_score(data) is None


def test_net_uses_handicap_strokes_not_course_handicap():
    # The trap: playerHandicap is the FULL-course handicap and must not be used.
    holes = [hole(n, 5) for n in range(10, 19)]
    data = with_course(holes, strokes=40, handicap=59, handicap_strokes=22)
    assert net_score(data) == 40 - evaluated_par(holes) - 22


def test_handicap_strokes_defaults_to_zero():
    assert handicap_strokes(bundle()) == 0


def test_net_score_reproduces_garmin_score_when_strokes_are_consistent():
    holes = [hole(n, 5) for n in range(1, 10)]
    data = with_course(holes, strokes=45, handicap=18, handicap_strokes=9)
    close = relative_score(data) - 9
    assert net_score(data) == close


def test_format_relative_signs():
    assert format_relative(12) == "+12"
    assert format_relative(-3) == "-3"
    assert format_relative(0) == "E"
    assert format_relative(None) == "-"
