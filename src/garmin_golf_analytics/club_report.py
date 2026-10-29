#!/usr/bin/env python3
"""Club distance report built from the JSON bundles written by garmin_golf_fetch.py.

Prints, per club and per lie, the median TOTAL distance, the share of shots that
end on the fairway or the green, and the count of mishits. Percentiles alone hide
the thing that actually costs strokes: a club whose p25-p75 looks tight can still
put two thirds of its balls in the rough, and a median computed with tops and
chips mixed in describes a shot nobody plays.

Garmin records one "meters" value per shot, from the start point to the end
point: ground distance, roll included. Carry is NOT in the data and is never
reported here.

Usage:
    python club_report.py rounds/                 # all bundles in a directory
    python club_report.py rounds/ --lie TeeBox    # one lie only
    python club_report.py rounds/ --min-meters 40 --min-shots 5
    python club_report.py rounds/ --keep-excluded # keep Garmin's excluded rounds

Only shots actually tracked by the watch are present (Garmin records a fraction
of the swings played), so a club with n < 5 gets flagged low-confidence.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from typing import Iterable

from .rounds_common import load_bundles, played_holes, select

LIE_ORDER = ("TeeBox", "Fairway", "Rough", "Bunker", "Green", "Recovery")
GOOD_LIES = ("Fairway", "Green")
# The putter is a real club off the green on dry, fast turf: a putt hit from the
# green is a stroke of the short game, a putt hit from anywhere else is an
# approach and deserves its own row. Garmin gives both the same shotType.
PUTTER = "Putter"
# A shot this short is a top, a duff or a mis-hit: it never describes the club.
MISHIT_METERS = 60
# No distance floor by default: a floor applied to every club silently deletes
# the wedges from their own table, and mishits are already counted separately.
DEFAULT_MIN_METERS = 0.0
DEFAULT_MIN_SHOTS = 5

# Garmin only stores a single "meters" value per shot: the GPS distance from the
# start point to the end point, roll included. There is no carry in the data, so
# every number this report prints, and the floor below it, is a TOTAL distance.
DISTANCE_LABEL = "total (GPS, roll included)"


def percentile(values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile on a sorted list."""
    if not values:
        raise ValueError("percentile of empty list")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def iter_shots(bundles: Iterable[dict]) -> Iterable[dict]:
    for bundle in bundles:
        for hole_shots in bundle.get("shots", {}).values():
            yield from hole_shots


def collect(shots: Iterable[dict], min_meters: float, lie: str | None) -> dict[tuple, list[tuple[float, str]]]:
    """Group shots by (club, lie) as (distance, ending lie) pairs.

    A putt hit ON the green is dropped: it is short-game, not a club distance.
    A putt hit anywhere else is kept as "Putter (approach)", because Garmin tags
    both the same way and the off-green one is a real shot the player chose.
    """
    grouped: dict[tuple, list[tuple[float, str]]] = defaultdict(list)
    for shot in shots:
        meters = shot.get("meters")
        # clubId=0 means the watch could not identify the club: those shots
        # carry an UNKNOWN shotType and must never be shown as a "club".
        if not shot.get("clubId") or shot.get("excludeFromStats"):
            continue
        shot_lie = (shot.get("startLoc") or {}).get("lie") or "Unknown"
        end_lie = (shot.get("endLoc") or {}).get("lie") or "Unknown"
        if shot.get("shotType") == "PUTT" and shot_lie == "Green":
            continue
        # No name means an unmapped clubTypeId (or a club the watch faked):
        # an id in a club table is noise, and it cannot be compared to anything.
        club = shot.get("clubName")
        if not club:
            continue
        # Keep putts played off the green: they are approaches with a flat club.
        if club == PUTTER and shot_lie == "Green":
            continue
        if club == PUTTER:
            # A putt that never reaches the green is not an approach either.
            if end_lie != "Green":
                continue
            club = "Putter (approach)"
        if meters is None or meters < min_meters:
            continue
        if lie and shot_lie != lie:
            continue
        grouped[(club, shot_lie)].append((float(meters), end_lie))
    return grouped


def report(grouped: dict[tuple, list[tuple[float, str]]], min_shots: int) -> None:
    by_lie: dict[str, list[tuple[str, list[tuple[float, str]]]]] = defaultdict(list)
    for (club, lie), shots in grouped.items():
        by_lie[lie].append((club, shots))

    lies = sorted(by_lie, key=lambda name: (LIE_ORDER.index(name) if name in LIE_ORDER else 99, name))
    for lie in lies:
        print(f"\n## {lie}")
        print(f"{'club':22} {'n':>3} {'med':>6} {'good%':>6} {'max':>6} {'mishits':>8}   (total m)")
        rows = sorted(by_lie[lie], key=lambda row: -percentile([d for d, _ in row[1]], 0.5))
        for club, shots in rows:
            # The club's own floor: a wedge never plays 60 m, a driver never plays 12.
            floor = min(MISHIT_METERS, percentile([d for d, _ in shots], 0.5) * 0.5)
            played = [d for d, _ in shots if d >= floor]
            mishits = len(shots) - len(played)
            good = sum(1 for _, lie_out in shots if lie_out in GOOD_LIES)
            med = percentile(played, 0.5) if played else float("nan")
            good_pct = f"{100 * good / len(shots):5.0f}" if shots else "    -"
            flag = "  (low n)" if len(played) < min_shots else ""
            print(
                f"{club[:22]:22} {len(played):3d} {med:6.0f} {good_pct}% "
                f"{max(played) if played else float('nan'):6.0f} {mishits:8d}{flag}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", nargs="?", default="rounds", help="directory of round_*.json (default: rounds)")
    parser.add_argument("--lie", help="restrict to one lie (TeeBox, Fairway, Rough, ...)")
    parser.add_argument("--min-meters", type=float, default=DEFAULT_MIN_METERS,
                        help="drop shots below this total distance (default: no floor)")
    parser.add_argument("--min-shots", type=int, default=DEFAULT_MIN_SHOTS,
                        help=f"flag clubs under this sample size (default: {DEFAULT_MIN_SHOTS})")
    parser.add_argument("--min-holes", type=int, default=9,
                        help="drop rounds with fewer played holes (default: 9)")
    parser.add_argument("--keep-excluded", action="store_true",
                        help="also use rounds Garmin flagged excludeFromStats")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.directory):
        print(f"no such directory: {args.directory}", file=sys.stderr)
        return 2

    bundles = load_bundles(args.directory)
    if not bundles:
        print(f"no round_*.json in {args.directory}", file=sys.stderr)
        return 1

    # Same round selection as round_report.py: one sample, one set of rules.
    selection = select(bundles, args.min_holes, keep_excluded=args.keep_excluded)
    kept = [b for b in selection.kept if played_holes(b)]
    shots = list(iter_shots(kept))
    grouped = collect(shots, args.min_meters, args.lie)
    print(f"{selection.describe()}, {len(shots)} tracked shots, distances are {DISTANCE_LABEL}")
    if not grouped:
        print("no shot above the distance floor", file=sys.stderr)
        return 1
    report(grouped, args.min_shots)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())