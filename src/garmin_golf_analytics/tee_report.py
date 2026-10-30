"""Tee-shot accuracy: which club actually keeps the ball in play.

Distance told you how far each club goes. It did not tell you which one puts you
in the rough, and that is the question a tee shot answers. Garmin records the
outcome of the drive on each hole (`fairwayShotOutcome`) and names the club that
hit it, so the two can be joined per hole: no modelling, just a count.

An outcome Garmin left empty is not a hit and not a miss. It is counted in
`unknown` and excluded from the percentage, the same way an unmeasured putt is
excluded rather than assumed. A percentage computed over hits plus misses only
is the honest one.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable

from . import output
from .round_report import DEFAULT_MIN_HOLES
from .rounds_common import load_bundles, played_holes, select

DESCRIPTION = "Which club keeps your tee shot in play?"

HIT = "HIT"
LEFT = "LEFT"
RIGHT = "RIGHT"
OUTCOMES = (HIT, LEFT, RIGHT)
DEFAULT_MIN_TEE_SHOTS = 5


def tee_shots(bundle: dict) -> Iterable[tuple[dict, str]]:
    """(shot, hole number) for the first tee shot of each hole.

    A hole with two shots tagged TEE is not two tee shots: the first one is the
    drive, the rest is whatever `shotOrder` says happened after it. Taking them
    all would double-count the same hole's outcome.
    """
    for hole_number, shots in (bundle.get("shots") or {}).items():
        ordered = sorted(shots, key=lambda shot: shot.get("shotOrder") or 0)
        for shot in ordered:
            if shot.get("shotType") == "TEE":
                yield shot, str(hole_number)
                break


def outcome_of(bundle: dict, hole_number: str) -> str | None:
    """Garmin's fairway outcome for one hole, or None when it was not recorded."""
    for hole in bundle["scorecard"].get("holes", []):
        if str(hole.get("number")) == hole_number:
            value = hole.get("fairwayShotOutcome")
            return value if value in OUTCOMES else None
    return None


def tee_profile(bundles: list[dict]) -> list[dict]:
    """One record per club used off the tee, with its in-play rate.

    `percent` is over recorded outcomes only. `unknown` says how many holes had
    no outcome at all, so a club with 3 hits out of 3 and 20 unknown holes does
    not read as a 100 % club.
    """
    counts: dict[str, dict[str, int]] = {}
    for bundle in bundles:
        for shot, hole_number in tee_shots(bundle):
            club = shot.get("clubName") or "Unknown club"
            row = counts.setdefault(club, {"hit": 0, "left": 0, "right": 0, "unknown": 0})
            outcome = outcome_of(bundle, hole_number)
            row["unknown" if outcome is None else outcome.lower()] += 1

    records = []
    for club, row in counts.items():
        recorded = row["hit"] + row["left"] + row["right"]
        records.append({
            "club": club,
            "tee_shots": sum(row.values()),
            "hit": row["hit"],
            "left": row["left"],
            "right": row["right"],
            "unknown": row["unknown"],
            "recorded": recorded,
            "in_play_percent": round(100 * row["hit"] / recorded, 1) if recorded else None,
        })
    return sorted(records, key=lambda record: (-record["tee_shots"], record["club"]))


def report(records: list[dict], min_shots: int) -> list[str]:
    lines = [f"{'club':22} {'tee':>4} {'hit':>4} {'left':>5} {'right':>6} {'?':>4} {'in play':>8}"]
    lines.append("-" * 58)
    for record in records:
        rate = (f"{record['in_play_percent']:7.1f}%"
                if record["in_play_percent"] is not None else "       -")
        flag = "  (low n)" if record["recorded"] < min_shots else ""
        lines.append(
            f"{record['club'][:22]:22} {record['tee_shots']:4d} {record['hit']:4d} "
            f"{record['left']:5d} {record['right']:6d} {record['unknown']:4d} {rate:>8}{flag}"
        )
    lines.append("")
    lines.append("In play is over recorded outcomes only; '?' holes have no outcome in Garmin "
                 "and are left out of the percentage rather than assumed either way.")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gga-tee", description=DESCRIPTION)
    parser.add_argument("directory", nargs="?", default="rounds",
                        help="directory of round_*.json bundles (default: rounds)")
    parser.add_argument("--min-holes", type=int, default=DEFAULT_MIN_HOLES,
                        help=f"drop rounds with fewer played holes (default: {DEFAULT_MIN_HOLES})")
    parser.add_argument("--min-shots", type=int, default=DEFAULT_MIN_TEE_SHOTS,
                        help=f"flag a club under this many recorded tee outcomes "
                             f"(default: {DEFAULT_MIN_TEE_SHOTS})")
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
    records = tee_profile(kept)
    if not records:
        print("no tee shot recorded in the kept rounds", file=sys.stderr)
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
