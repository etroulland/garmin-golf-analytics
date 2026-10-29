"""Per-course breakdown: the same rounds, split by where they were played.

A single figure averages courses that have nothing in common. A links with deep
rough and a short parkland do not punish the same mistakes, so "I shoot +18"
can hide a course that eats you and one you own. `course.name` is in every
bundle, so this is a regrouping of figures the other reports already compute.

The splits respect the same selection rules as everything else, and a course
with one round is labelled rather than silently given the same weight as one
with twenty.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

from .round_report import (
    BLOWUP_STROKES,
    DEFAULT_MIN_HOLES,
    putt_status,
)
from .rounds_common import load_bundles, played_holes, select
from .scoring import net_score, played_par, relative_score
from . import output

DESCRIPTION = "Same rounds, one row per course: where you actually score."

DEFAULT_MIN_ROUNDS = 1


def course_name(bundle: dict) -> str:
    """The course as Garmin names it, never blank.

    A bundle with no course name is still a round: calling it "unknown" keeps it
    in the total instead of dropping a played round from a report about courses.
    """
    name = (bundle.get("course") or {}).get("name")
    return name.strip() if isinstance(name, str) and name.strip() else "Unknown course"


def course_records(bundles: list[dict]) -> list[dict]:
    """One record per course, with the per-hole figures the player report uses.

    Per hole and per round only: a course played six times and one played once
    cannot be compared on raw totals.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for bundle in bundles:
        groups[course_name(bundle)].append(bundle)

    records = []
    for name, rounds in groups.items():
        holes = [hole for bundle in rounds for hole in played_holes(bundle)]
        if not holes:
            continue
        strokes = [hole["strokes"] for hole in holes]
        # Putts are per round and a course is many rounds: only the rounds Garmin
        # measured count, the others would drag the average toward 2 putts a hole.
        measured = []
        for bundle in rounds:
            round_putts, _label = putt_status(bundle, played_holes(bundle))
            if round_putts:
                measured.extend(round_putts)
        records.append({
            "course": name,
            "rounds": len(rounds),
            "holes": len(holes),
            "strokes_per_hole": round(sum(strokes) / len(holes), 2),
            "to_par_per_hole": round(sum(relative_score(b) or 0 for b in rounds) / len(holes), 2),
            "net_to_par_per_hole": round(sum(net_score(b) or 0 for b in rounds) / len(holes), 2),
            "best_to_par": min((relative_score(b) for b in rounds if relative_score(b) is not None),
                               default=None),
            "worst_to_par": max((relative_score(b) for b in rounds if relative_score(b) is not None),
                                default=None),
            "blowup_percent": round(100 * sum(1 for value in strokes if value >= BLOWUP_STROKES)
                                    / len(holes), 1),
            "putts_per_hole": round(sum(measured) / len(measured), 2) if measured else None,
            "putts_measured_rounds": sum(1 for b in rounds
                                         if putt_status(b, played_holes(b))[0] is not None),
            "par_played": sum(played_par(b) or 0 for b in rounds),
        })
    return sorted(records, key=lambda record: (-record["rounds"], record["course"]))


def report(records: list[dict], min_rounds: int) -> list[str]:
    lines = [f"{'course':34} {'rnd':>3} {'holes':>5} {'stk/h':>5} {'par/h':>5} {'net/h':>6} "
             f"{'best':>5} {'worst':>5} {'blow%':>6} {'putt/h':>6}"]
    lines.append("-" * 92)
    for record in records:
        short = record["course"] if len(record["course"]) <= 34 else record["course"][:31] + "..."
        flag = "  (one round)" if record["rounds"] < min_rounds else ""
        putts = (f"{record['putts_per_hole']:6.2f}" if record["putts_per_hole"] is not None
                 else "     -")
        lines.append(
            f"{short:34} {record['rounds']:3d} {record['holes']:5d} "
            f"{record['strokes_per_hole']:5.2f} {record['to_par_per_hole']:+5.2f} "
            f"{record['net_to_par_per_hole']:+6.2f} "
            f"{_signed(record['best_to_par']):>5} {_signed(record['worst_to_par']):>5} "
            f"{record['blowup_percent']:5.1f}% {putts}{flag}"
        )
    lines.append("")
    lines.append("Every figure is per hole or per round, so a course played once sits next to "
                 "one played twenty times. Putts/round counts measured rounds only.")
    return lines


def _signed(value: int | None) -> str:
    return "-" if value is None else f"{value:+d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gga-courses", description=DESCRIPTION)
    parser.add_argument("directory", nargs="?", default="rounds",
                        help="directory of round_*.json bundles (default: rounds)")
    parser.add_argument("--min-holes", type=int, default=DEFAULT_MIN_HOLES,
                        help=f"drop rounds with fewer played holes (default: {DEFAULT_MIN_HOLES})")
    parser.add_argument("--min-rounds", type=int, default=4,
                        help="flag a course played fewer times than this (default: 4)")
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
    records = course_records(kept)
    if not records:
        print("no usable round", file=sys.stderr)
        return 1
    if args.format != "text":
        output.write(records, args.format)
        return 0
    print(selection.describe())
    print("")
    for line in report(records, args.min_rounds):
        print(line)
    return 0


def entry_point() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entry_point()
