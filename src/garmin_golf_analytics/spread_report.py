"""Dispersion per club: the median is a promise the shots do not always keep.

Two players with a 170 m median play the same club and do not play the same
game. One hits 165 to 175 every time, the other alternates 140 and 200. The
median is identical; the club on the tee is not the same decision.

Every figure here is computed from the same shot sample as `gga-clubs`, through
the same mishit floor, so a 170 m median means the same thing in both commands.
A shrinking band means a club you can count on; a growing one means a club you
are guessing with, whatever the median says.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys

from .club_report import (
    DEFAULT_MIN_METERS,
    DEFAULT_MIN_SHOTS,
    MISHIT_METERS,
    bundle_pars,
    collect_by_kind,
    iter_shots,
    percentile,
)
from .round_report import DEFAULT_MIN_HOLES
from .rounds_common import load_bundles, played_holes, select
from . import output

DESCRIPTION = "How repeatable is each club: spread, floor and the share of short ones."

SHORT_FRACTION = 0.8


def spread_profile(bundles: list[dict], min_meters: float = DEFAULT_MIN_METERS) -> list[dict]:
    """One record per club and shot kind: median, spread and dispersion.

    `spread_m` is the p25..p75 band, the honest range of a club: half its shots
    land inside it. `cv_percent` is the standard deviation over the median, so a
    driver and a wedge can be compared despite being 100 m apart. `short_percent`
    counts shots under 80 % of the median: the tops and the half-shots that do
    not travel, which a mean quietly averages away.
    """
    grouped = collect_by_kind(iter_shots(bundles), min_meters, bundle_pars(bundles))
    records = []
    for (club, kind), distances in sorted(grouped.items()):
        median_distance = percentile(distances, 0.5)
        floor = min(MISHIT_METERS, median_distance * 0.5)
        played = [distance for distance in distances if distance >= floor]
        if not played:
            continue
        median_played = percentile(played, 0.5)
        low, high = percentile(played, 0.25), percentile(played, 0.75)
        deviation = statistics.pstdev(played) if len(played) > 1 else 0.0
        records.append({
            "club": club,
            "shot_kind": kind,
            "n": len(played),
            "median_m": round(median_played, 1),
            "p25_m": round(low, 1),
            "p75_m": round(high, 1),
            "spread_m": round(high - low, 1),
            "stdev_m": round(deviation, 1),
            "cv_percent": round(100 * deviation / median_played, 1) if median_played else None,
            "short_m": round(median_played * SHORT_FRACTION, 1),
            "short_percent": round(100 * sum(1 for d in played if d < median_played * SHORT_FRACTION)
                                   / len(played), 1),
        })
    return records


def report(records: list[dict], min_shots: int) -> list[str]:
    lines = [f"{'club':20} {'shot':11} {'n':>4} {'p25':>5} {'med':>5} {'p75':>5} {'band':>5} "
             f"{'sd':>5} {'cv%':>5} {'short%':>7}"]
    lines.append("-" * 82)
    for record in records:
        flag = "  (low n)" if record["n"] < min_shots else ""
        lines.append(
            f"{record['club'][:20]:20} {record['shot_kind'][:11]:11} {record['n']:4d} "
            f"{record['p25_m']:5.0f} {record['median_m']:5.0f} {record['p75_m']:5.0f} "
            f"{record['spread_m']:5.0f} {record['stdev_m']:5.1f} "
            f"{_cv(record['cv_percent']):>5} {record['short_percent']:6.1f}%{flag}"
        )
    lines.append("")
    lines.append(f"band = p25..p75, half the shots land inside it. cv% = standard deviation over "
                 f"the median, comparable across clubs. short% = shots under {SHORT_FRACTION:.0%} "
                 f"of the median.")
    return lines


def _cv(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gga-spread", description=DESCRIPTION)
    parser.add_argument("directory", nargs="?", default="rounds",
                        help="directory of round_*.json bundles (default: rounds)")
    parser.add_argument("--min-meters", type=float, default=DEFAULT_MIN_METERS,
                        help="drop shots below this total distance (default: no floor)")
    parser.add_argument("--min-shots", type=int, default=DEFAULT_MIN_SHOTS,
                        help=f"flag clubs under this sample size (default: {DEFAULT_MIN_SHOTS})")
    parser.add_argument("--min-holes", type=int, default=DEFAULT_MIN_HOLES,
                        help=f"drop rounds with fewer played holes (default: {DEFAULT_MIN_HOLES})")
    parser.add_argument("--keep-excluded", action="store_true",
                        help="also use rounds Garmin flagged excludeFromStats")
    parser.add_argument("--format", choices=("text", "json", "csv"), default="text",
                        help="text for a person, json or csv for anything that will outlive the "
                             "glance (default: text); json/csv go to stdout alone")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.directory):
        print(f"no such directory: {args.directory}", file=sys.stderr)
        return 2
    bundles = load_bundles(args.directory)
    if not bundles:
        print(f"no round_*.json in {args.directory}", file=sys.stderr)
        return 1

    selection = select(bundles, args.min_holes, keep_excluded=args.keep_excluded)
    kept = [bundle for bundle in selection.kept if played_holes(bundle)]
    records = spread_profile(kept, args.min_meters)
    if not records:
        print("no tracked shot in the kept rounds", file=sys.stderr)
        return 1
    if args.format != "text":
        output.write(records, args.format)
        return 0
    print(selection.describe())
    print("")
    for line in report(records, args.min_shots):
        print(line)
    return 0


def entry_point() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entry_point()
