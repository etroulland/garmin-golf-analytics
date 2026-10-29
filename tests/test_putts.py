"""Putts: Garmin cannot measure them without the club sensors, so the report must say so."""
from __future__ import annotations

from conftest import bundle, hole
from garmin_golf_analytics.round_report import putt_status, putts_are_measured, usable_putts


def holes(*putts):
    return [hole(i + 1, 5, putts=p) for i, p in enumerate(putts)]


def test_constant_putts_are_garmin_fill_not_a_game():
    data = bundle(holes=holes(2, 2, 2, 2, 2, 2, 2, 2, 2))
    assert usable_putts(data, data["scorecard"]["holes"]) is None


def test_missing_putts_return_none():
    data = bundle(holes=holes(None, None))
    assert usable_putts(data, data["scorecard"]["holes"]) is None


def test_varying_putts_are_usable():
    data = bundle(holes=holes(1, 2, 3, 2))
    assert usable_putts(data, data["scorecard"]["holes"]) == [1, 2, 3, 2]


def test_sensor_off_manual_entry_is_labelled_as_manual():
    data = bundle(holes=holes(1, 2, 3), sensor=False)
    putts, label = putt_status(data, data["scorecard"]["holes"])
    assert putts == [1, 2, 3]
    assert "manual" in label
    assert "sensor off" in label


def test_sensor_on_is_labelled_sensor():
    data = bundle(holes=holes(1, 2, 3), sensor=True)
    putts, label = putt_status(data, data["scorecard"]["holes"])
    assert putts == [1, 2, 3]
    assert label == "sensor"


def test_constant_fill_with_sensor_on_still_dropped():
    # Defensive: a constant count is a fill, not a measured game.
    data = bundle(holes=holes(2, 2, 2), sensor=True)
    putts, label = putt_status(data, data["scorecard"]["holes"])
    assert putts is None
    assert "no putt data" in label


def test_no_putt_data_label_when_sensor_off_and_no_entry():
    data = bundle(holes=holes(None, None), sensor=False)
    putts, label = putt_status(data, data["scorecard"]["holes"])
    assert putts is None
    assert label == "no putt data (sensor off, no entry)"


def test_putts_are_measured_reads_the_flag():
    assert putts_are_measured(bundle(sensor=True)) is True
    assert putts_are_measured(bundle(sensor=False)) is False
    data = bundle()
    del data["scorecard"]["sensorOnPutter"]
    assert putts_are_measured(data) is False
