"""garmin_golf_fetch.py: club mapping, hole-by-hole shot merge, target selection.

No network: the Garmin client is replaced by a stub exposing connectapi and
get_golf_scorecard, which is all the module ever calls.
"""
from __future__ import annotations

import json

import pytest
from conftest import shot

import garmin_golf_analytics.garmin_golf_fetch as fetch


class StubClient:
    def __init__(self, shot_payloads=None, scorecard=None, summaries=None, fail_holes=(),
                 clubs=None):
        self.shot_payloads = shot_payloads or {}
        self.scorecard = scorecard or {}
        self.summaries = summaries or []
        self.clubs = clubs or []
        self.fail_holes = set(fail_holes)
        self.calls = []

    def connectapi(self, path, params=None):
        hole = int((params or {}).get("hole-numbers"))
        self.calls.append(hole)
        if hole in self.fail_holes:
            raise RuntimeError("boom")
        return self.shot_payloads.get(hole, {"holeShots": []})

    @property
    def garmin_golf_shot(self):
        return "/golf/shots"

    def get_golf_summary(self, start, limit):
        return {"scorecardSummaries": self.summaries}

    def get_golf_scorecard(self, scid):
        return self.scorecard

    def get_golf_club_stats(self):
        return self.clubs


def scorecard(strokes_list):
    holes = [{"number": i + 1, "strokes": s} for i, s in enumerate(strokes_list)]
    total = sum(s for s in strokes_list if s is not None)
    return {"scorecardDetails": [{"scorecard": {
        "startTime": "2026-09-01 08:00:00", "strokes": total,
        "holes": holes,
    }}]}


def test_build_club_map_without_reference_is_empty(capsys):
    # Silent: the API map is the default path and a missing --zipref is not news.
    assert fetch.build_club_map(None) == {}
    assert capsys.readouterr().err == ""


def test_build_club_map_maps_ids_to_names(tmp_path):
    (tmp_path / "Golf-CLUB.json").write_text(json.dumps({"data": [
        {"id": 7, "clubTypeId": 3, "retired": False},
        {"id": 9, "clubTypeId": 4, "retired": True},
    ]}))
    (tmp_path / "Golf-CLUB_TYPES.json").write_text(json.dumps({"data": [
        {"value": 3, "name": "7 Iron", "loftAngle": 34},
        {"value": 4, "name": "Driver", "loftAngle": 10},
    ]}))
    club_map = fetch.build_club_map(str(tmp_path))
    assert club_map[7]["name"] == "7 Iron"
    assert club_map[7]["loft"] == 34
    assert club_map[9]["retired"] is True


def test_build_club_map_missing_files(tmp_path, capsys):
    assert fetch.build_club_map(str(tmp_path)) == {}
    assert "club reference missing" in capsys.readouterr().err


def test_build_club_map_unknown_type_keeps_id(tmp_path):
    (tmp_path / "Golf-CLUB.json").write_text(json.dumps({"data": [{"id": 7, "clubTypeId": 99}]}))
    (tmp_path / "Golf-CLUB_TYPES.json").write_text(json.dumps({"data": [{"value": 3, "name": "7 Iron"}]}))
    assert fetch.build_club_map(str(tmp_path))[7]["name"] is None


def test_fetch_shots_merges_holes():
    client = StubClient({1: {"holeShots": [{"holeNumber": 1, "shots": [shot("Driver", 200)]}]},
                         2: {"holeShots": [{"holeNumber": 2, "shots": [shot("7 Iron", 120)]}]}})
    shots = fetch.fetch_shots(client, 999, 2)
    assert sorted(shots) == [1, 2]
    assert len(shots[1]) == 1


def test_fetch_shots_survives_a_failing_hole(capsys):
    client = StubClient({1: {"holeShots": [{"holeNumber": 1, "shots": []}]}}, fail_holes={2})
    shots = fetch.fetch_shots(client, 999, 2)
    assert list(shots) == [1]
    assert "hole 2 skipped" in capsys.readouterr().err


def test_fetch_shots_accumulates_two_tees_of_one_hole():
    client = StubClient({1: {"holeShots": [
        {"holeNumber": 1, "shots": [shot("Driver", 200)]},
        {"holeNumber": 1, "shots": [shot("7 Iron", 120)]},
    ]}})
    assert len(fetch.fetch_shots(client, 999, 1)[1]) == 2


def test_attach_clubs_sets_name_and_loft():
    shots = {1: [{"clubId": 7}]}
    fetch.attach_clubs(shots, {7: {"name": "7 Iron", "loft": 34}})
    assert shots[1][0]["clubName"] == "7 Iron"
    assert shots[1][0]["clubLoft"] == 34


def test_attach_clubs_unknown_club_leaves_none():
    shots = {1: [{"clubId": 404}]}
    fetch.attach_clubs(shots, {})
    assert shots[1][0]["clubName"] is None


def test_fetch_round_counts_played_holes_and_queries_all_holes():
    client = StubClient(scorecard=scorecard([4, 5, None]))
    bundle = fetch.fetch_round(client, 42, {})
    assert bundle["playedHoles"] == 2
    assert client.calls == [1, 2, 3]
    assert bundle["scorecard"]["strokes"] == 9


def test_fetch_round_defaults_to_18_holes_when_scorecard_is_empty():
    client = StubClient(scorecard={"scorecardDetails": [{"scorecard": {"holes": []}}]})
    fetch.fetch_round(client, 42, {})
    assert client.calls == list(range(1, 19))


def test_select_targets_explicit_scid():
    client = StubClient(summaries=[{"id": 1, "startTime": "2026-09-01"}])
    assert fetch.select_targets(client, None, 77) == [77]


def test_select_targets_latest_round():
    client = StubClient(summaries=[{"id": 5, "startTime": "2026-10-01"},
                                   {"id": 4, "startTime": "2026-09-01"}])
    assert fetch.select_targets(client, None, None) == [5]


def test_select_targets_empty_feed():
    assert fetch.select_targets(StubClient(), None, None) == []


def test_select_targets_window_filters_by_date():
    client = StubClient(summaries=[
        {"id": 5, "startTime": "2020-01-01 08:00:00"},
        {"id": 6, "startTime": "2999-01-01 08:00:00"},
    ])
    assert fetch.select_targets(client, 30, None) == [6]


def test_main_requires_a_token_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fetch, "login", lambda store: pytest.fail("must not log in"))
    assert fetch.main(["--tokenstore", str(tmp_path / "missing")]) == 2
    assert "token store not found" in capsys.readouterr().err


def test_main_writes_one_bundle_per_round(tmp_path, monkeypatch, capsys):
    client = StubClient(scorecard=scorecard([4, 5]),
                        summaries=[{"id": 42, "startTime": "2026-09-01 08:00:00"}])
    monkeypatch.setattr(fetch, "login", lambda store: client)
    store = tmp_path / "tokens"
    store.mkdir()
    outdir = tmp_path / "rounds"
    assert fetch.main(["--tokenstore", str(store), "--outdir", str(outdir)]) == 0
    written = list(outdir.glob("round_*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text())
    assert payload["playedHoles"] == 2
    assert "OK 2026-09-01" in capsys.readouterr().out


def test_main_reports_a_failing_scorecard(tmp_path, monkeypatch, capsys):
    class Boom(StubClient):
        def get_golf_scorecard(self, scid):
            raise RuntimeError("api down")

    client = Boom(summaries=[{"id": 42, "startTime": "2026-09-01 08:00:00"}])
    monkeypatch.setattr(fetch, "login", lambda store: client)
    store = tmp_path / "tokens"
    store.mkdir()
    assert fetch.main(["--tokenstore", str(store), "--outdir", str(tmp_path / "r")]) == 1
    assert "FAIL 42" in capsys.readouterr().err


def test_main_no_round_in_window(tmp_path, monkeypatch, capsys):
    client = StubClient()
    monkeypatch.setattr(fetch, "login", lambda store: client)
    store = tmp_path / "tokens"
    store.mkdir()
    assert fetch.main(["--tokenstore", str(store)]) == 1
    assert "no round in the requested window" in capsys.readouterr().err


def test_missing_garminconnect_exits_at_import(tmp_path):
    """The module must fail loudly when the library is absent, not KeyError later."""
    import subprocess
    import sys

    blocker = tmp_path / "garminconnect.py"
    blocker.write_text("raise ImportError('simulated missing library')\n")
    # An installed package would win over the blocker on sys.path, so shadow it
    # by pointing PYTHONPATH at the blocker only and importing from anywhere but
    # the repo root: the module must be found through the package name.
    result = subprocess.run(
        [sys.executable, "-c", "from garmin_golf_analytics import garmin_golf_fetch"],
        cwd=str(tmp_path), capture_output=True, text=True,
        env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert "garminconnect is missing: pip install garminconnect" in result.stdout + result.stderr


def test_build_course_parses_hole_pars_into_a_hole_number_map():
    course = fetch.build_course([{"name": "Golf De Casteljaloux", "city": "Casteljaloux",
                                  "country": "France", "holePars": "453534453444344454",
                                  "frontNinePar": 36, "backNinePar": 36, "roundPar": 72}])
    assert course["name"] == "Golf De Casteljaloux"
    assert course["roundPar"] == 72
    assert course["pars"][1] == 4
    assert course["pars"][9] == 3   # 9th digit of the string, not a fixed par
    assert course["pars"][18] == 4
    assert sorted(course["pars"]) == list(range(1, 19))


def test_build_course_of_a_nine_hole_course():
    course = fetch.build_course([{"holePars": "333444533", "frontNinePar": 32}])
    assert sorted(course["pars"]) == list(range(1, 10))


def test_build_course_without_snapshots_is_empty():
    assert fetch.build_course(None) == {}
    assert fetch.build_course([]) == {}


def test_build_course_tolerates_missing_hole_pars():
    assert fetch.build_course([{"name": "nowhere"}])["pars"] == {}


def test_fetch_round_keeps_the_course_block():
    payload = {"scorecardDetails": [{"scorecard": {
        "startTime": "2026-09-01 08:00:00", "strokes": 9, "holes": [{"number": 1, "strokes": 4}]}}],
        "courseSnapshots": [{"name": "Golf Club St. Meard", "holePars": "333444533"}]}
    client = StubClient(scorecard=payload)
    result = fetch.fetch_round(client, 42, {})
    assert result["course"]["name"] == "Golf Club St. Meard"
    assert result["course"]["pars"][1] == 3


def test_fetch_round_survives_a_response_without_course_snapshots():
    client = StubClient(scorecard=scorecard([4]))
    assert fetch.fetch_round(client, 42, {})["course"] == {}


def test_club_map_from_api_uses_the_type_table():
    client = StubClient()
    client.clubs = [{"id": 1, "clubTypeId": 1, "retired": False, "flexTypeId": "STIFF"},
                    {"id": 2, "clubTypeId": 23, "retired": False},
                    {"id": 3, "clubTypeId": 999, "retired": True}]
    mapped = fetch.club_map_from_api(client)
    assert mapped[1]["name"] == "Driver"
    assert mapped[2]["name"] == "Putter"
    assert mapped[3]["name"] is None
    assert mapped[3]["retired"] is True


def test_club_map_from_api_survives_a_failing_endpoint():
    client = StubClient()

    def boom():
        raise RuntimeError("429")

    client.get_golf_club_stats = boom
    assert fetch.club_map_from_api(client) == {}


def test_club_type_names_only_holds_checked_types():
    # A guessed id mislabels every shot: the table must stay small and verified.
    assert fetch.CLUB_TYPE_NAMES[1] == "Driver"
    assert fetch.CLUB_TYPE_NAMES[14] == "6 Iron"
    assert fetch.CLUB_TYPE_NAMES[19] == "Pitching Wedge"
    assert fetch.CLUB_TYPE_NAMES[23] == "Putter"
    assert 22 not in fetch.CLUB_TYPE_NAMES


def test_fetch_round_drops_garmins_net_score():
    client = StubClient(scorecard=scorecard([4]))
    client.scorecard["scorecardDetails"][0]["scorecard"]["score"] = -12
    assert "score" not in fetch.fetch_round(client, 42, {})["scorecard"]
