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
import io
import os
import sys
from collections import defaultdict
from typing import Iterable

from .rounds_common import load_bundles, played_holes, select
from . import output

LIE_ORDER = ("TeeBox", "Fairway", "Rough", "Bunker", "Green", "Recovery")
GOOD_LIES = ("Fairway", "Green")
# The putter is a real club off the green on dry, fast turf: a putt hit from the
# green is a stroke of the short game, a putt hit from anywhere else is an
# approach and deserves its own row. Garmin gives both the same shotType.
PUTTER = "Putter"
# A shot this short is a top, a duff or a mis-hit: it never describes the club.
MISHIT_METERS = 60
# A shot starting this close to the green and finishing on it is a chip, not an
# approach, whatever Garmin called it: 14 of the Gap Wedge's UNKNOWN shots ran
# 10 to 45 m from the fringe onto the green. Below this distance the club is not
# being used to fly the ball to the green, it is being used around it.
CHIP_RANGE_METERS = 50
# No distance floor by default: a floor applied to every club silently deletes
# the wedges from their own table, and mishits are already counted separately.
DEFAULT_MIN_METERS = 0.0
DEFAULT_MIN_SHOTS = 5

# Garmin labels a shot TEE, APPROACH, CHIP, LAYUP, PUTT or UNKNOWN. UNKNOWN is
# Garmin having no idea, not a shot type of its own: it is a large share of the
# tracked shots and dropping it silently shrank every sample. Only the putts are
# refused here; everything else is kept and labelled with what the lie and the
# shot's position in the hole actually say it was.
SHOT_TYPE_LABELS = {
    "TEE": "Tee",
    "APPROACH": "Approach",
    "CHIP": "Chip",
    "LAYUP": "Layup",
    "PITCH": "Pitch",
    "RECOVERY": "Recovery",
}
UNKNOWN_LABEL = "Unclassified"
# Garmin puts `lie == "TeeBox"` on the FIRST shot of a hole, whatever club was
# hit. A par 4 opened with a 7-iron is tagged TeeBox, so the lie alone cannot
# decide whether an UNKNOWN shot was a tee shot. The hole's par came from the
# course snapshot: a par 4 or 5 opened on TeeBox with a club short of a driver
# is the player laying up, not driving.
PAR_THAT_ALLOWS_A_LAYUP = (4, 5)
LONG_CLUBS = ("Driver", "1 Wood", "3 Wood", "2 Wood", "4 Wood")
LAYUP_ON_TEE = "Layup (tee)"
SHORT_GAME_SHOT_TYPES = ("CHIP", "PITCH", "RECOVERY")
MISHIT_LABEL = "Mishit"
# The order a player thinks about a hole: off the tee, then the second shot,
# then the short game, with whatever could not be classified last.
KIND_ORDER = ("Tee", LAYUP_ON_TEE, "Approach", "Layup", "Pitch", "Chip", "Recovery", "Putt", UNKNOWN_LABEL)


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
    """Flatten every shot of every bundle, carrying its hole number and the par.

    `hole` is injected here because the shot kind cannot be decided without it:
    a first shot on a par 3 is a tee shot, the same shot on a par 4 may be a
    layup. `par` comes from the course snapshot stored in the bundle.
    """
    for bundle in bundles:
        pars = (bundle.get("course") or {}).get("pars") or {}
        for hole_number, hole_shots in bundle.get("shots", {}).items():
            for shot in hole_shots:
                enriched = dict(shot)
                enriched.setdefault("hole", hole_number)
                enriched.setdefault("par", pars.get(str(hole_number)))
                yield enriched


def bundle_pars(bundles: Iterable[dict]) -> dict:
    """Hole number -> par, merged across bundles (one course per key in practice)."""
    pars: dict = {}
    for bundle in bundles:
        pars.update((bundle.get("course") or {}).get("pars") or {})
    return pars


def is_first_shot(shot: dict) -> bool:
    """Garmin numbers the shots of a hole in play order, starting at 1."""
    return (shot.get("shotOrder") or 1) == 1


def shot_kind(shot: dict, club: str, hole_par: int | None) -> str:
    """What the shot actually was, from Garmin's label and the lie.

    Garmin's own `shotType` is used when it is specific. When it says UNKNOWN,
    the lie, the shot's position in the hole and the distance decide:
      * on the green                          -> Putt
      * first shot of a par 4 or 5, long club -> Tee
      * first shot of a par 4 or 5, short club -> Layup (tee)
      * first shot of a par 3                 -> Tee
      * finishing on the green from under CHIP_RANGE_METERS -> Chip
      * anything else                         -> Unclassified
    """
    kind = shot.get("shotType")
    shot_lie = (shot.get("startLoc") or {}).get("lie") or "Unknown"
    end_lie = (shot.get("endLoc") or {}).get("lie") or "Unknown"
    # The putter labels stay as they are: "Putter (approach)" is a deliberate
    # row in the lie table, and calling those strokes "Chip" here would make the
    # two views of the same shot disagree.
    if club.startswith(PUTTER):
        return "Putt"
    if kind == "PUTT":
        return "Putt"
    if kind in SHORT_GAME_SHOT_TYPES:
        # Garmin already said chip/pitch/recovery: nothing to add.
        return SHOT_TYPE_LABELS[kind]
    if shot_lie == "Green":
        return "Putt"
    if kind in SHOT_TYPE_LABELS:
        # Garmin named it and the shot starts on the tee box: its word stands.
        return SHOT_TYPE_LABELS[kind]
    if shot_lie == "TeeBox" and is_first_shot(shot):
        if hole_par in PAR_THAT_ALLOWS_A_LAYUP and club not in LONG_CLUBS:
            return LAYUP_ON_TEE
        return SHOT_TYPE_LABELS["TEE"]
    meters = shot.get("meters")
    if end_lie == "Green" and meters is not None and meters < CHIP_RANGE_METERS:
        return SHOT_TYPE_LABELS["CHIP"]
    return UNKNOWN_LABEL


def collect(shots: Iterable[dict], min_meters: float, lie: str | None,
            pars: dict | None = None) -> dict[tuple, list[tuple[float, str]]]:
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


def collect_by_kind(shots: Iterable[dict], min_meters: float, pars: dict | None = None) -> dict[tuple, list[float]]:
    """Same rules, but grouped by (club, shot kind) so the profile is visible.

    A median computed over tees, approaches and chips of one club describes no
    shot anybody plays. `pars` maps a hole number to its par; without it the
    first shot of a par 4 cannot be told apart from a layup.
    """
    grouped: dict[tuple, list[float]] = defaultdict(list)
    for shot in shots:
        meters = shot.get("meters")
        if not shot.get("clubId") or shot.get("excludeFromStats"):
            continue
        shot_lie = (shot.get("startLoc") or {}).get("lie") or "Unknown"
        end_lie = (shot.get("endLoc") or {}).get("lie") or "Unknown"
        club = shot.get("clubName")
        if not club:
            continue
        if club == PUTTER and shot_lie == "Green":
            continue
        if club == PUTTER and end_lie != "Green":
            continue
        if meters is None or meters < min_meters:
            continue
        hole_par = shot.get("par")
        if hole_par is None:
            hole_par = (pars or {}).get(str(shot.get("hole")))
        kind = shot_kind(shot, club, hole_par)
        grouped[(club, kind)].append(float(meters))
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
            floor = min(MISHIT_METERS, percentile(distances, 0.5) * 0.5)
            played = [d for d in distances if d >= floor]
            mishits = len(distances) - len(played)
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
    for (club, lie), shots in sorted(collect(iter_shots(bundles), min_meters, None, bundle_pars(bundles)).items()):
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


def split_mishits(distances: list[float]) -> tuple[list[float], int]:
    """Split a club's shots into played and mishits using the club's own floor.

    A wedge never plays 60 m, a driver never plays 12: the floor is relative to
    the club's own median, capped at MISHIT_METERS. Both the table and the
    machine-readable output go through here so they cannot disagree.
    """
    if not distances:
        return [], 0
    floor = min(MISHIT_METERS, percentile(distances, 0.5) * 0.5)
    played = [distance for distance in distances if distance >= floor]
    return played, len(distances) - len(played)


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
        kinds = {kind: sum(len(v) for (_, k), v in by_kind.items() if k == kind) for kind in
                 set(k for (_, k) in by_kind)}
        total = sum(kinds.values())
        unknown = kinds.get(UNKNOWN_LABEL, 0)
        print(f"{total} shots by type, {unknown} ({100 * unknown / total:.0f}%) not classifiable")
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
