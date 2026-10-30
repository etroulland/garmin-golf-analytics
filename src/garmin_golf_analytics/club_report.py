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

The rules that decide what a shot is and which shots belong in a table live in
`shot_classification.py`; this module only groups, renders and dispatches.

Usage:
    gga-clubs rounds/                 # all bundles in a directory
    gga-clubs rounds/ --lie TeeBox    # one lie only
    gga-clubs rounds/ --min-meters 40 --min-shots 5
    gga-clubs rounds/ --keep-excluded # keep Garmin's excluded rounds

Only shots actually tracked by the watch are present (Garmin records a fraction
of the swings played), so a club with n < 5 gets flagged low-confidence.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from collections import defaultdict

from . import output
from .round_report import DEFAULT_MIN_HOLES
from .rounds_common import load_bundles, played_holes, select
from .shot_classification import (
    CHIP_RANGE_METERS,
    GOOD_LIES,
    KIND_ORDER,
    LAYUP_ON_TEE,
    LIE_ORDER,
    LONG_CLUBS,
    MISHIT_LABEL,
    MISHIT_METERS,
    PAR_THAT_ALLOWS_A_LAYUP,
    PUTTER,
    SHORT_GAME_SHOT_TYPES,
    SHOT_TYPE_LABELS,
    UNKNOWN_LABEL,
    bundle_pars,
    collect,
    collect_by_kind,
    is_first_shot,
    iter_shots,
    percentile,
    shot_kind,
    split_mishits,
)

# No distance floor by default: a floor applied to every club silently deletes
# the wedges from their own table, and mishits are already counted separately.
DEFAULT_MIN_METERS = 0.0
DEFAULT_MIN_SHOTS = 5

# Garmin only stores a single "meters" value per shot: the GPS distance from the
# start point to the end point, roll included. There is no carry in the data, so
# every number this report prints, and the floor below it, is a TOTAL distance.
DISTANCE_LABEL = "total (GPS, roll included)"

# Re-exported for the callers that imported them from here before the split.
__all__ = [
    "CHIP_RANGE_METERS", "DEFAULT_MIN_METERS", "DEFAULT_MIN_SHOTS", "DISTANCE_LABEL",
    "GOOD_LIES", "KIND_ORDER", "LAYUP_ON_TEE", "LIE_ORDER", "LONG_CLUBS", "MISHIT_LABEL",
    "MISHIT_METERS", "PAR_THAT_ALLOWS_A_LAYUP", "PUTTER", "SHORT_GAME_SHOT_TYPES",
    "SHOT_TYPE_LABELS", "UNKNOWN_LABEL", "bundle_pars", "club_records", "collect",
    "collect_by_kind", "entry_point", "is_first_shot", "iter_shots", "main",
    "matrix_cells", "percentile", "print_matrix", "report", "report_by_kind",
    "report_kind_matrix", "report_matrix", "shot_kind", "split_mishits",
]


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
            # The club's own floor, shared with the machine-readable records:
            # a wedge never plays 60 m, a driver never plays 12.
            played, mishits = split_mishits([distance for distance, _ in shots])
            good = sum(1 for _, lie_out in shots if lie_out in GOOD_LIES)
            med = percentile(played, 0.5) if played else float("nan")
            good_pct = f"{100 * good / len(shots):5.0f}" if shots else "    -"
            flag = "  (low n)" if len(played) < min_shots else ""
            print(
                f"{club[:22]:22} {len(played):3d} {med:6.0f} {good_pct}% "
                f"{max(played) if played else float('nan'):6.0f} {mishits:8d}{flag}"
            )


def report_by_kind(grouped: dict[tuple, list[float]], min_shots: int) -> None:
    """Print the same numbers split by what the shot was, not only by the lie.

    A chip and a tee shot of the same club are two different swings: averaging
    them into one row describes neither. Rows are ordered by club so a club's
    profile reads top to bottom.
    """
    by_club: dict[str, list[tuple[str, list[float]]]] = defaultdict(list)
    for (club, kind), distances in grouped.items():
        by_club[club].append((kind, distances))

    # Order the rows the way a player thinks about a hole: off the tee, then the
    # second shot, then the short game. Unclassified last, so the honest gap in
    # Garmin's data is impossible to overlook.
    kind_rank = {label: index for index, label in enumerate(KIND_ORDER)}
    for club in sorted(by_club, key=lambda name: -percentile(by_club[name][0][1], 0.5)):
        print(f"\n## {club}")
        print(f"{'shot':20} {'n':>3} {'med':>6} {'p75':>6} {'max':>6} {'mishits':>8}   (total m)")
        for kind, distances in sorted(by_club[club], key=lambda row: kind_rank.get(row[0], 99)):
            played, mishits = split_mishits(distances)
            flag = "  (low n)" if len(played) < min_shots else ""
            print(
                f"{kind[:20]:20} {len(played):3d} {percentile(played, 0.5) if played else float('nan'):6.0f} "
                f"{percentile(played, 0.75) if played else float('nan'):6.0f} "
                f"{max(played) if played else float('nan'):6.0f} {mishits:8d}{flag}"
            )


def matrix_cells(grouped: dict[tuple, list], columns: tuple[str, ...]) -> dict[tuple[str, str], list[float]]:
    """Keep only the wanted columns, dropping an empty list so it prints as `-`."""
    cells: dict[tuple[str, str], list[float]] = {}
    for (club, column), values in grouped.items():
        if column not in columns:
            continue
        kept = [float(value[0]) if isinstance(value, tuple) else float(value) for value in values]
        if kept:
            cells[(club, column)] = kept
    return cells


def print_matrix(cells: dict[tuple[str, str], list[float]], columns: tuple[str, ...],
                 min_shots: int, title: str, empty_message: str) -> bool:
    """Render clubs in rows, `columns` in columns, median and n in each cell.

    Returns False when there was nothing to print, so the caller can exit 1
    instead of reporting success on an empty table.
    """
    if not cells:
        print(empty_message, file=sys.stderr)
        return False

    # Order by the first column that has data, so an empty first column does not
    # scramble the whole table.
    def order_key(name: str) -> float:
        for column in columns:
            distances = cells.get((name, column))
            if distances:
                return -percentile(distances, 0.5)
        return 0.0

    clubs = sorted({club for club, _ in cells}, key=order_key)
    total_width = 22 + 11 * len(columns)
    print(title)
    print(f"\n{'club':22}" + "".join(f"{column[:10]:>11}" for column in columns))
    print("-" * total_width)
    for club in clubs:
        row = f"{club[:22]:22}"
        for column in columns:
            distances = cells.get((club, column))
            if not distances:
                row += f"{'-':>11}"
                continue
            med = percentile(distances, 0.5)
            flag = "*" if len(distances) < min_shots else ""
            row += f"{f'{med:.0f} ({len(distances)}){flag}':>11}"
        print(row)
    print(f"\n* fewer than {min_shots} tracked shots: the median is not a distance yet")
    return True


def report_matrix(grouped: dict[tuple, list[tuple[float, str]]], min_shots: int, lies: tuple[str, ...]) -> bool:
    """One table: clubs as rows, lies as columns, the median distance in each cell.

    Reading a club across a row is the question actually asked on the course:
    does the 7-iron still go the same distance off the rough as off the fairway?
    A cell shows the median and its sample size, `-` when nothing was tracked
    there. Cells under `min_shots` are flagged, because a median over two shots
    is a coincidence, not a distance.
    """
    return print_matrix(matrix_cells(grouped, lies), lies, min_shots,
                        "median total distance per club and lie (m), n in parentheses",
                        "no shot in those lies")


def report_kind_matrix(grouped: dict[tuple, list[float]], min_shots: int,
                       kinds: tuple[str, ...]) -> bool:
    """Same table, but the columns are what the shot was instead of the lie.

    Lies say where the ball was, shot kinds say what the player was trying to
    do. A 6-iron off the tee going 158 m and off the fairway going 121 m is an
    average nobody plays; splitting by kind shows whether the fairway number is
    a layup or an approach before blaming the lie.
    """
    return print_matrix(matrix_cells(grouped, kinds), kinds, min_shots,
                        "median total distance per club and shot kind (m), n in parentheses",
                        "no shot of that kind")


def club_records(bundles: list[dict], min_meters: float) -> list[dict]:
    """One record per club and lie, the same rows `report()` prints.

    Kept separate from the printed table on purpose: the table applies one rule
    (the club's own mishit floor) and this must apply the identical one, so the
    floor lives in `split_mishits` and both read it.
    """
    records = []
    for (club, lie), shots in sorted(collect(iter_shots(bundles), min_meters, None,
                                             bundle_pars(bundles)).items()):
        played, mishits = split_mishits([distance for distance, _ in shots])
        if not played:
            continue
        good = sum(1 for _, lie_out in shots if lie_out in GOOD_LIES)
        records.append({
            "club": club,
            "lie": lie,
            "n": len(played),
            "median_m": round(percentile(played, 0.5), 1),
            "max_m": round(max(played), 1),
            "good_lie_percent": round(100 * good / len(shots), 1),
            "mishits": mishits,
        })
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", nargs="?", default="rounds", help="directory of round_*.json (default: rounds)")
    parser.add_argument("--lie", help="restrict to one lie (TeeBox, Fairway, Rough, ...)")
    parser.add_argument("--min-meters", type=float, default=DEFAULT_MIN_METERS,
                        help="drop shots below this total distance (default: no floor)")
    parser.add_argument("--min-shots", type=int, default=DEFAULT_MIN_SHOTS,
                        help=f"flag clubs under this sample size (default: {DEFAULT_MIN_SHOTS})")
    parser.add_argument("--min-holes", type=int, default=DEFAULT_MIN_HOLES,
                        help=f"drop rounds with fewer played holes (default: {DEFAULT_MIN_HOLES})")
    parser.add_argument("--by-shot-type", action="store_true",
                        help="split each club by what the shot was (tee, approach, chip, ...) "
                             "instead of by lie only")
    parser.add_argument("--matrix", nargs="?", const="", default=None, metavar="COLUMNS",
                        help="one table with clubs in rows and comma-separated COLUMNS; "
                             "defaults to the TeeBox,Fairway lies, or to the shot kinds "
                             "with --matrix-axis kind")
    parser.add_argument("--matrix-axis", choices=("lie", "kind"), default="lie",
                        help="what the --matrix columns mean: a lie or a shot kind (default: lie)")
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

    # Same round selection as round_report.py: one sample, one set of rules.
    selection = select(bundles, args.min_holes, keep_excluded=args.keep_excluded)
    kept = [b for b in selection.kept if played_holes(b)]
    if args.format != "text":
        records = club_records(kept, args.min_meters)
        if not records:
            print("no shot above the distance floor", file=sys.stderr)
            return 1
        output.write(records, args.format)
        return 0
    shots = list(iter_shots(kept))
    pars = bundle_pars(kept)
    print(f"{selection.describe()}, {len(shots)} tracked shots, distances are {DISTANCE_LABEL}")
    if args.matrix is not None:
        default_columns = "TeeBox,Fairway" if args.matrix_axis == "lie" else "Tee,Approach,Chip"
        raw = args.matrix or default_columns
        columns = tuple(name.strip() for name in raw.split(",") if name.strip())
        known = LIE_ORDER if args.matrix_axis == "lie" else KIND_ORDER
        unknown = [name for name in columns if name not in known]
        if unknown:
            print(f"unknown {args.matrix_axis}(s): {', '.join(unknown)}; known: {', '.join(known)}",
                  file=sys.stderr)
            return 2
        if args.matrix_axis == "lie":
            grouped = collect(shots, args.min_meters, None, pars)
            if not grouped:
                print("no shot above the distance floor", file=sys.stderr)
                return 1
            return 0 if report_matrix(grouped, args.min_shots, columns) else 1
        else:
            by_kind = collect_by_kind(shots, args.min_meters, pars)
            if not by_kind:
                print("no shot above the distance floor", file=sys.stderr)
                return 1
            return 0 if report_kind_matrix(by_kind, args.min_shots, columns) else 1
    if args.by_shot_type:
        by_kind = collect_by_kind(shots, args.min_meters, pars)
        if not by_kind:
            print("no shot above the distance floor", file=sys.stderr)
            return 1
        # Say how much of the sample Garmin's own labels could not describe, so
        # the share of guessed rows is never implied.
        kinds: dict[str, int] = {}
        for (_, kind), distances in by_kind.items():
            kinds[kind] = kinds.get(kind, 0) + len(distances)
        total = sum(kinds.values())
        unsigned = kinds.get(UNKNOWN_LABEL, 0)
        print(f"{total} shots by type, {unsigned} ({100 * unsigned / total:.0f}%) not classifiable")
        report_by_kind(by_kind, args.min_shots)
        return 0
    grouped = collect(shots, args.min_meters, args.lie, pars)
    if not grouped:
        print("no shot above the distance floor", file=sys.stderr)
        return 1
    report(grouped, args.min_shots)
    return 0


def entry_point(argv: list[str] | None = None) -> int:
    """Console-script wrapper: `gga-clubs rounds/ | head` must not crash.

    Closing the pipe raises BrokenPipeError on the next print, and Python then
    flushes stdout again at exit, which raises a second one and prints a
    traceback. Both are silenced and the process exits 0 like any other Unix
    tool whose reader went away.
    """
    try:
        return main(argv)
    except BrokenPipeError:
        # Point fd 1 at /dev/null so the flush at interpreter exit cannot raise
        # a second BrokenPipeError. stdout has no fd when it is captured (pytest,
        # an embedding app): then there is nothing left to flush anyway.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError, io.UnsupportedOperation):
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(entry_point())
