#!/usr/bin/env python3
"""Club distance report built from the JSON bundles written by garmin_golf_fetch.py.

Prints median/p75/p90 carry distance per club, split by lie, so the numbers stay
honest: chipping shots must never be averaged into full-swing numbers, and one
club can read long off the tee and short from the rough.

Usage:
    python club_report.py rounds/                 # all bundles in a directory
    python club_report.py rounds/ --lie TeeBox    # one lie only
    python club_report.py rounds/ --min-meters 40 --min-shots 5

Only shots actually tracked by the watch are present (Garmin records a fraction
of the swings played), so a club with n < 5 gets flagged low-confidence.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Iterable

LIE_ORDER = ("TeeBox", "Fairway", "Rough", "Bunker", "Green", "Recovery")
DEFAULT_MIN_METERS = 40
DEFAULT_MIN_SHOTS = 5


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


def load_bundles(directory: str) -> list[dict[str, Any]]:
    bundles = []
    for name in sorted(os.listdir(directory)):
        if not (name.startswith("round_") and name.endswith(".json")):
            continue
        with open(os.path.join(directory, name), encoding="utf-8") as handle:
            bundles.append(json.load(handle))
    return bundles


def iter_shots(bundles: Iterable[dict]) -> Iterable[dict]:
    for bundle in bundles:
        for hole_shots in bundle.get("shots", {}).values():
            yield from hole_shots


def collect(shots: Iterable[dict], min_meters: float, lie: str | None) -> dict[tuple, list[float]]:
    """Group shot distances by (club, lie).

    club falls back to the raw clubId when no reference export was supplied.
    """
    grouped: dict[tuple, list[float]] = defaultdict(list)
    for shot in shots:
        meters = shot.get("meters")
        # clubId=0 means the watch could not identify the club: those shots
        # carry an UNKNOWN shotType and must never be shown as a "club".
        if not shot.get("clubId") or shot.get("excludeFromStats"):
            continue
        club = shot.get("clubName") or f"clubId:{shot.get('clubId')}"
        shot_lie = (shot.get("startLoc") or {}).get("lie") or "Unknown"
        if meters is None or meters < min_meters:
            continue
        if lie and shot_lie != lie:
            continue
        grouped[(club, shot_lie)].append(float(meters))
    return grouped


def report(grouped: dict[tuple, list[float]], min_shots: int) -> None:
    by_lie: dict[str, list[tuple[str, list[float]]]] = defaultdict(list)
    for (club, lie), distances in grouped.items():
        by_lie[lie].append((club, distances))

    lies = sorted(by_lie, key=lambda name: (LIE_ORDER.index(name) if name in LIE_ORDER else 99, name))
    for lie in lies:
        print(f"\n## {lie}")
        print(f"{'club':22} {'n':>3} {'med':>6} {'p75':>6} {'p90':>6} {'max':>6}")
        rows = sorted(by_lie[lie], key=lambda row: -percentile(row[1], 0.5))
        for club, distances in rows:
            flag = "  (low n)" if len(distances) < min_shots else ""
            print(
                f"{club[:22]:22} {len(distances):3d} "
                f"{percentile(distances, 0.5):6.0f} {percentile(distances, 0.75):6.0f} "
                f"{percentile(distances, 0.9):6.0f} {max(distances):6.0f}{flag}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", nargs="?", default="rounds", help="directory of round_*.json (default: rounds)")
    parser.add_argument("--lie", help="restrict to one lie (TeeBox, Fairway, Rough, ...)")
    parser.add_argument("--min-meters", type=float, default=DEFAULT_MIN_METERS,
                        help=f"drop shots below this carry, drops chips (default: {DEFAULT_MIN_METERS})")
    parser.add_argument("--min-shots", type=int, default=DEFAULT_MIN_SHOTS,
                        help=f"flag clubs under this sample size (default: {DEFAULT_MIN_SHOTS})")
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"no such directory: {args.directory}", file=sys.stderr)
        return 2

    bundles = load_bundles(args.directory)
    if not bundles:
        print(f"no round_*.json in {args.directory}", file=sys.stderr)
        return 1

    shots = list(iter_shots(bundles))
    grouped = collect(shots, args.min_meters, args.lie)
    print(f"{len(bundles)} rounds, {len(shots)} tracked shots")
    if not grouped:
        print("no shot above the distance floor", file=sys.stderr)
        return 1
    report(grouped, args.min_shots)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
