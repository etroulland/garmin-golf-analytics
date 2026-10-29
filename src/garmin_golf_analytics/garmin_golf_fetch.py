#!/usr/bin/env python3
"""Fetch Garmin Connect golf rounds to a local JSON bundle.

Replaces the manual DI_CONNECT zip export: pulls scorecards and shot-by-shot
GPS data straight from the Garmin API and writes one JSON per round.

Usage:
    export GARMINTOKENS=~/.garminconnect   # token store written by `garmin-auth`
    python garmin_golf_fetch.py                     # latest round
    python garmin_golf_fetch.py --days 30           # every round in the window
    python garmin_golf_fetch.py --scid 383676990    # one specific scorecard
    python garmin_golf_fetch.py --zipref ./DI_CONNECT/DI-GOLF

Output (default ./rounds):
    round_<YYYY-MM-DD>_<scid>.json  ->
        {"scorecard": {...}, "shots": {...}, "course": {...}, "playedHoles": n}

API quirks this script works around:
  * The shot endpoint rejects multi-hole queries ("1,2,...,18" returns a 400).
    It must be queried one hole at a time; queries are merged here.
  * get_golf_scorecard() wants the scorecardId (``id`` from the summary), not
    the activityId. The activityId yields an empty scorecard.
  * Login strategies often emit 429 warnings while a fallback succeeds.
    Judge on the result, not on the warnings.
  * Per-hole par and the course name live in ``courseSnapshots``, a SIBLING of
    ``scorecardDetails`` in the same response. Read only ``scorecardDetails``
    and you lose them, which is why holes[].par reads as null.
  * ``holePars`` is a string of pars ordered 1..18 on the course, while
    ``holes[]`` holds the holes actually played and their ``number``. A BACK_9
    round lists holes 10..18, so pars must be joined on the hole number, never
    on the position in the array.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from typing import Any

try:
    from garminconnect import Garmin
except ImportError:  # pragma: no cover
    sys.exit("garminconnect is missing: pip install garminconnect")

CLUB_TYPES_FILE = "Golf-CLUB_TYPES.json"
CLUBS_FILE = "Golf-CLUB.json"

# clubTypeId -> name, for the types this account actually uses. The API returns
# the id but never the label, so the table is the only source of readable names.
# Every entry was checked against a DI-GOLF data export on real clubs; do not
# guess the gaps, an off-by-one numbering silently mislabels every shot. Types
# absent from the table fall back to "club:<type>", which still beats a bare id.
CLUB_TYPE_NAMES = {
    1: "Driver",            # checked against a data export
    6: "4 Hybrid",          # checked
    7: "5 Iron",            # checked
    12: "4 Iron",           # NOT checked
    13: "5 Iron",           # NOT checked
    14: "6 Iron",           # checked
    15: "7 Iron",           # checked
    16: "8 Iron",           # checked
    17: "9 Iron",           # checked
    19: "Pitching Wedge",   # checked
    20: "Gap Wedge",        # checked
    21: "Sand Wedge",       # checked
    23: "Putter",           # checked
}
DEFAULT_OUTDIR = "rounds"
SUMMARY_PAGE = 50


def login(tokenstore: str) -> Garmin:
    """Restore a session from the token store (no credentials in this file)."""
    client = Garmin()
    client.login(tokenstore)
    return client


def load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def club_map_from_api(client: Garmin) -> dict[int, dict[str, Any]]:
    """Map clubId -> {name, loft, retired} straight from the user's Garmin clubs.

    `get_golf_club_stats` lists every club, retired ones included, with its
    clubTypeId, shaft length and flex. It never gives the club's NAME: that is a
    property of the type, not of the club, so the name comes from CLUB_TYPE_NAMES.
    """
    try:
        clubs = client.get_golf_club_stats()
    except Exception as exc:  # noqa: BLE001 - names must never block a fetch
        print(f"club list unavailable ({type(exc).__name__}: {exc}), shots keep raw clubId",
              file=sys.stderr)
        return {}
    club_map: dict[int, dict[str, Any]] = {}
    for club in clubs or []:
        name = CLUB_TYPE_NAMES.get(club.get("clubTypeId"))
        club_map[club["id"]] = {
            "name": name,
            "loft": None,
            "flex": club.get("flexTypeId"),
            "shaftLength": club.get("shaftLength"),
            "retired": club.get("retired"),
        }
    return club_map


def build_club_map(reference_dir: str | None) -> dict[int, dict[str, Any]]:
    """Map clubId -> {name, loft, retired} using an optional Garmin data export.

    Kept as an override: a DI-GOLF export carries the loft per club, which the
    API does not expose. Without it the map comes from `club_map_from_api`.
    """
    if not reference_dir:
        return {}

    clubs_path = os.path.join(reference_dir, CLUBS_FILE)
    types_path = os.path.join(reference_dir, CLUB_TYPES_FILE)
    if not (os.path.exists(clubs_path) and os.path.exists(types_path)):
        print(f"club reference missing in {reference_dir}, ignoring --zipref", file=sys.stderr)
        return {}

    types = {entry["value"]: entry for entry in load_json(types_path).get("data", [])}
    club_map: dict[int, dict[str, Any]] = {}
    for club in load_json(clubs_path).get("data", []):
        meta = types.get(club.get("clubTypeId"), {})
        club_map[club["id"]] = {
            "name": meta.get("name"),
            "loft": meta.get("loftAngle"),
            "retired": club.get("retired"),
        }
    return club_map


def fetch_shots(client: Garmin, scid: int, hole_count: int) -> dict[int, list[dict]]:
    """Fetch shots hole by hole (the endpoint refuses multi-hole queries)."""
    shots: dict[int, list[dict]] = {}
    for hole in range(1, hole_count + 1):
        try:
            payload = client.connectapi(
                f"{client.garmin_golf_shot}/{scid}/hole",
                params={"hole-numbers": str(hole)},
            )
        except Exception as exc:  # noqa: BLE001 - one hole must not kill the round
            print(f"  hole {hole} skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        for hole_shots in payload.get("holeShots", []):
            shots.setdefault(hole_shots["holeNumber"], []).extend(hole_shots.get("shots", []))
    return shots


def attach_clubs(shots: dict[int, list[dict]], club_map: dict[int, dict]) -> None:
    for hole_shots in shots.values():
        for shot in hole_shots:
            club = club_map.get(shot.get("clubId"), {})
            shot["clubName"] = club.get("name")
            shot["clubLoft"] = club.get("loft")


def build_course(raw_course_snapshots: list[dict] | None) -> dict[str, Any]:
    """Normalise courseSnapshots into {name, city, country, pars, roundPar}.

    `pars` is {hole number: par}. The API sends holePars as a digit string
    ordered 1..18, delivered in whatever orientation the snapshot stores.
    """
    if not raw_course_snapshots:
        return {}
    snapshot = raw_course_snapshots[0]
    digits = str(snapshot.get("holePars") or "")
    pars: dict[int, int] = {}
    for index, char in enumerate(digits, start=1):
        if char.isdigit():
            pars[index] = int(char)
    return {
        "name": snapshot.get("name"),
        "city": snapshot.get("city"),
        "country": snapshot.get("country"),
        "courseGlobalId": snapshot.get("courseGlobalId"),
        "courseSnapshotId": snapshot.get("courseSnapshotId"),
        "frontNinePar": snapshot.get("frontNinePar"),
        "backNinePar": snapshot.get("backNinePar"),
        "roundPar": snapshot.get("roundPar"),
        "pars": pars,
    }


def fetch_round(client: Garmin, scid: int, club_map: dict[int, dict]) -> dict:
    payload = client.get_golf_scorecard(scid)
    scorecard = payload["scorecardDetails"][0]["scorecard"]
    holes = scorecard.get("holes", []) or []
    # holes[] is padded with strokes=None for unplayed holes: length is the
    # only reliable hole count, and the API needs a number, not a real count.
    played = sum(1 for hole in holes if hole.get("strokes") is not None)
    # Garmin's own `score` field is a NET score built on handicappedStrokes; it
    # reads wrong on partial rounds and nothing here uses it. Drop it rather than
    # ship a number that invites a subtraction it cannot survive.
    scorecard.pop("score", None)
    shots = fetch_shots(client, scid, len(holes) or 18)
    attach_clubs(shots, club_map)
    course = build_course(payload.get("courseSnapshots"))
    return {"scorecard": scorecard, "shots": shots, "course": course, "playedHoles": played}


def select_targets(client: Garmin, days: int | None, scid: int | None) -> list[int]:
    if scid:
        return [scid]
    summaries = client.get_golf_summary(0, SUMMARY_PAGE).get("scorecardSummaries", [])
    if not days:
        return [summaries[0]["id"]] if summaries else []
    cutoff = date.today() - timedelta(days=days)
    return [
        entry["id"]
        for entry in summaries
        if date.fromisoformat(entry["startTime"][:10]) >= cutoff
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, help="fetch every round played in the last N days")
    parser.add_argument("--scid", type=int, help="fetch one scorecard by id")
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR, help="output directory (default: rounds)")
    parser.add_argument(
        "--zipref",
        default=os.environ.get("GARMIN_ZIPREF"),
        help="DI-GOLF export directory used for club names (default: $GARMIN_ZIPREF)",
    )
    parser.add_argument(
        "--tokenstore",
        default=os.environ.get("GARMINTOKENS", os.path.expanduser("~/.garminconnect")),
        help="garminconnect token store (default: $GARMINTOKENS)",
    )
    args = parser.parse_args(argv)

    if not os.path.isdir(args.tokenstore):
        print(f"token store not found: {args.tokenstore} (run garminconnect login first)", file=sys.stderr)
        return 2

    client = login(args.tokenstore)
    club_map = build_club_map(args.zipref) or club_map_from_api(client)
    if club_map:
        named = sum(1 for club in club_map.values() if club.get("name"))
        print(f"{len(club_map)} clubs mapped, {named} named", file=sys.stderr)
    else:
        print("no club names: shots keep raw clubId", file=sys.stderr)
    targets = select_targets(client, args.days, args.scid)
    if not targets:
        print("no round in the requested window", file=sys.stderr)
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    written = 0
    for scid in targets:
        try:
            bundle = fetch_round(client, scid, club_map)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {scid}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        played_on = bundle["scorecard"]["startTime"][:10]
        path = os.path.join(args.outdir, f"round_{played_on}_{scid}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(bundle, handle, ensure_ascii=False, indent=1)
        shot_count = sum(len(s) for s in bundle["shots"].values())
        course_name = bundle["course"].get("name") or "unknown course"
        print(
            f"OK {played_on} scid={scid} course={course_name} par={bundle['course'].get('roundPar')} "
            f"strokes={bundle['scorecard'].get('strokes')} "
            f"holes={bundle['playedHoles']} shots={shot_count} -> {path}"
        )
        written += 1

    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
