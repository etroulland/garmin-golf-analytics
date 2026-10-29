"""Shot type and TeeBox honesty: what the numbers are allowed to claim.

Garmin's own labels are imperfect and the report used to inherit that silently.
These tests pin down the three rules that make the table honest:
  * an UNKNOWN shot is kept, not dropped, and only the unlabelled ones say so
  * `lie == "TeeBox"` alone never proves a tee shot
  * the share of the sample that could not be classified is printed
"""
from __future__ import annotations

import pytest

from garmin_golf_analytics.club_report import (
    LAYUP_ON_TEE,
    UNKNOWN_LABEL,
    bundle_pars,
    collect_by_kind,
    iter_shots,
    shot_kind,
)


def s(club="Driver", meters=200.0, lie="Fairway", kind="APPROACH", order=1,
      end_lie="Fairway", club_id=100, hole=1, par=4):
    return {
        "clubId": club_id, "clubName": club, "meters": meters, "shotOrder": order,
        "shotType": kind, "startLoc": {"lie": lie}, "endLoc": {"lie": end_lie},
        "hole": hole, "par": par,
    }


# --- shot_kind: Garmin's label wins when it says something -------------------

@pytest.mark.parametrize("garmin,expected", [
    ("TEE", "Tee"),
    ("APPROACH", "Approach"),
    ("CHIP", "Chip"),
    ("LAYUP", "Layup"),
    ("PUTT", "Putt"),
])
def test_garmin_labels_are_kept(garmin, expected):
    assert shot_kind(s(kind=garmin), "8 Iron", 4) == expected


def test_unknown_on_the_green_is_a_putt():
    assert shot_kind(s(kind="UNKNOWN", lie="Green"), "Putter", 4) == "Putt"


def test_unknown_with_no_lie_is_still_counted_as_unclassified():
    """A shot Garmin cannot describe is reported, never silently dropped."""
    shot = s(kind="UNKNOWN")
    shot["startLoc"] = {}
    assert shot_kind(shot, "7 Iron", 4) == UNKNOWN_LABEL


# --- the TeeBox lie: first shot of the hole, not a tee shot ------------------

def test_first_shot_on_a_par_3_is_a_tee_shot_whatever_the_club():
    assert shot_kind(s(kind="UNKNOWN", lie="TeeBox", club="9 Iron"), "9 Iron", 3) == "Tee"


def test_first_shot_on_a_par_3_with_an_iron_is_not_a_layup():
    """There is nothing to lay up to from the tee of a par 3."""
    assert shot_kind(s(kind="UNKNOWN", lie="TeeBox"), "7 Iron", 3) == "Tee"


def test_first_shot_on_a_par_4_with_a_driver_is_a_tee_shot():
    assert shot_kind(s(kind="UNKNOWN", lie="TeeBox"), "Driver", 4) == "Tee"


def test_first_shot_on_a_par_4_with_an_iron_is_a_layup_not_a_tee_shot():
    """The bug: Garmin tags every first shot TeeBox, so the iron looked like a tee shot."""
    assert shot_kind(s(kind="UNKNOWN", lie="TeeBox"), "7 Iron", 4) == LAYUP_ON_TEE


def test_first_shot_on_a_par_5_with_a_hybrid_is_a_layup():
    assert shot_kind(s(kind="UNKNOWN", lie="TeeBox"), "4 Hybrid", 5) == LAYUP_ON_TEE


def test_first_shot_without_a_known_par_is_a_plain_tee_shot():
    """No par in the snapshot: assume the tee rather than invent a layup."""
    assert shot_kind(s(kind="UNKNOWN", lie="TeeBox"), "7 Iron", None) == "Tee"


def test_second_shot_from_the_teebox_lie_is_not_a_tee_shot():
    """shotOrder > 1 means the player is no longer teeing off, whatever the lie says."""
    assert shot_kind(s(kind="UNKNOWN", lie="TeeBox", order=2), "Driver", 4) == UNKNOWN_LABEL


def test_unknown_shot_ending_on_the_green_from_close_range_is_a_chip():
    """Gap Wedge UNKNOWN shots ran 10 to 45 m onto the green: that is a chip."""
    shot = s(kind="UNKNOWN", lie="Rough", meters=23.0, end_lie="Green")
    assert shot_kind(shot, "Gap Wedge", 4) == "Chip"


def test_unknown_shot_ending_on_the_green_from_far_away_is_not_a_chip():
    shot = s(kind="UNKNOWN", lie="Rough", meters=95.0, end_lie="Green")
    assert shot_kind(shot, "Gap Wedge", 4) == UNKNOWN_LABEL


def test_unknown_short_shot_that_misses_the_green_is_not_a_chip():
    shot = s(kind="UNKNOWN", lie="Rough", meters=23.0, end_lie="Bunker")
    assert shot_kind(shot, "Gap Wedge", 4) == UNKNOWN_LABEL


def test_a_tee_typed_shot_on_a_par_4_short_club_keeps_garmins_word():
    """Only UNKNOWN is second-guessed; Garmin saying TEE is accepted."""
    assert shot_kind(s(kind="TEE", lie="TeeBox"), "5 Iron", 4) == "Tee"


# --- iter_shots carries the par, without which nothing above can work --------

def test_iter_shots_carries_the_hole_par_from_the_course_snapshot():
    bundle = {"course": {"pars": {"1": 4}}, "shots": {"1": [{"meters": 150.0, "clubId": 1, "clubName": "7 Iron"}]}}
    shot = next(iter_shots([bundle]))
    assert shot["par"] == 4
    assert shot["hole"] == "1"


def test_iter_shots_leaves_an_annotated_shot_alone():
    """A shot already carrying its par is not overwritten by the bundle's."""
    bundle = {"course": {"pars": {"1": 4}}, "shots": {"1": [{"meters": 150.0, "par": 3, "hole": "1"}]}}
    assert next(iter_shots([bundle]))["par"] == 3


def test_bundle_pars_merges_the_courses():
    assert bundle_pars([{"course": {"pars": {"1": 4}}}, {"course": {"pars": {"2": 3}}}]) == {"1": 4, "2": 3}


def test_bundle_pars_survives_a_bundle_without_a_course():
    assert bundle_pars([{}, {"course": {"pars": {"1": 5}}}]) == {"1": 5}


# --- collect_by_kind: the UNKNOWN shots are in the numbers -------------------

def test_unknown_shots_are_kept_in_the_by_kind_grouping():
    """The old table dropped them; 23% of the sample vanished without a word."""
    shots = [s(kind="UNKNOWN", lie="Rough", meters=120.0)]
    grouped = collect_by_kind(shots, 0.0, {"1": 4})
    assert grouped[("Driver", UNKNOWN_LABEL)] == [120.0]


def test_unclassifiable_first_shot_on_a_par_4_is_not_lost():
    shots = [s(kind="UNKNOWN", lie="TeeBox", club="5 Iron", meters=150.0)]
    grouped = collect_by_kind(shots, 0.0, {"1": 4})
    assert grouped[("5 Iron", LAYUP_ON_TEE)] == [150.0]


def test_putts_from_the_green_stay_out_of_the_club_table():
    shots = [s(kind="PUTT", lie="Green", club="Putter", meters=2.0, end_lie="Green")]
    assert collect_by_kind(shots, 0.0, {"1": 4}) == {}


def test_a_putter_shot_off_the_green_is_labelled_putt_not_chip():
    """Both views must agree: the lie table calls it "Putter (approach)", so
    the shot-kind view cannot call the same stroke a chip."""
    shot = s(kind="PUTT", lie="Fairway", club="Putter", meters=14.0, end_lie="Green")
    assert shot_kind(shot, "Putter (approach)", 4) == "Putt"


def test_a_putt_from_the_fringe_is_kept_as_a_putt():
    shots = [s(kind="PUTT", lie="Fairway", club="Putter", meters=14.0, end_lie="Green")]
    grouped = collect_by_kind(shots, 0.0, {"1": 4})
    assert grouped[("Putter", "Putt")] == [14.0]


def test_a_putt_that_misses_the_green_is_still_dropped():
    shots = [s(kind="PUTT", lie="Fairway", club="Putter", meters=14.0, end_lie="Rough")]
    assert collect_by_kind(shots, 0.0, {"1": 4}) == {}


def test_shots_without_a_club_name_are_dropped():
    shots = [s(club=None), s(club_id=0)]
    assert collect_by_kind(shots, 0.0, {"1": 4}) == {}


def test_the_distance_floor_is_still_honoured_in_the_kind_grouping():
    shots = [s(kind="APPROACH", meters=5.0)]
    assert collect_by_kind(shots, 20.0, {"1": 4}) == {}
