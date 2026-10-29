#!/usr/bin/env python3
"""Round debrief from the bundles written by garmin_golf_fetch.py.

Focuses on the numbers that actually decide a score: strokes per hole
distribution, blow-up holes, penalties, and putts - with the traps handled:

  * holes[].par is null, but the par of every hole is in
    `courseSnapshots[].holePars`, kept in the bundle's `course` block. Scoring is
    reported relative to the par of the holes actually played, joined on the
    hole number (a BACK_9 round starts at hole 10). `scorecard.score` itself is
    not used: it mixes in the course handicap and breaks on partial rounds;
  * Garmin cannot detect putts without its club sensors: with the putter sensor
    off, the count is either manual entry or Garmin's constant fill of 2 on
    every hole. A round with a constant putts value AND sensorOnPutter off is
    reported as NO PUTT DATA, never averaged. Manual entry with the sensor off
    is flagged `putts=manual` so no one reads it as sensor data;
  * practice, abandoned and Garmin-excluded rounds are filtered out in one
    place (rounds_common.py) shared with club_report.py.

Usage:
    python round_report.py rounds/
    python round_report.py rounds/ --min-holes 9
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from statistics import median

from .hole_sync import coverage
from .rounds_common import load_bundles, played_holes, select
from .scoring import format_relative, hole_pars, net_score, played_par, relative_score

DEFAULT_MIN_HOLES = 9
BLOWUP_STROKES = 7


def usable_putts(bundle: dict, holes: list[dict]) -> list[int] | None:
    """Return per-hole putts, or None when there is no meaningful putt data.

    With the putter sensor off, Garmin measures nothing: the value is either
    manual entry or its own default fill of a constant 2 on every hole. A
    constant count is Garmin's fill, never a real game, whatever the sensor
    says, so it is dropped. Returns None when there is nothing to average.
    """
    putts = [h.get("putts") for h in holes if h.get("putts") is not None]
    if not putts:
        return None
    if len(set(putts)) == 1:
        return None
    return putts


def putts_are_measured(bundle: dict) -> bool:
    """True only when the watch actually counted the putts."""
    return bool(bundle["scorecard"].get("sensorOnPutter"))


def putt_status(bundle: dict, holes: list[dict]) -> tuple[list[int] | None, str]:
    """(putts, label). Label is what the report prints for this round."""
    putts = usable_putts(bundle, holes)
    measured = putts_are_measured(bundle)
    if putts is None:
        return None, "no putt data (sensor off, no entry)"
    return putts, ("sensor" if measured else "manual entry, sensor off")


def summarise(bundles: list[dict], min_holes: int, keep_excluded: bool = False) -> None:
    selection = select(bundles, min_holes, keep_excluded=keep_excluded)
    kept = selection.kept
    print(selection.describe())
    for bundle in selection.excluded:
        print(f"  excluded by Garmin: {bundle['scorecard']['startTime'][:10]}", file=sys.stderr)

    stroke_counts: Counter[int] = Counter()
    per_hole: list[int] = []
    penalties = 0
    putts_all: list[int] = []
    putt_rounds = 0
    to_par: list[int | None] = []
    net_to_par: list[int | None] = []
    known: list[bool] = []

    for bundle in kept:
        holes = played_holes(bundle)
        played_on = bundle["scorecard"]["startTime"][:10]
        strokes = [h["strokes"] for h in holes]
        penalties += sum(h.get("penalties") or 0 for h in holes)
        stroke_counts.update(strokes)
        per_hole.extend(strokes)

        putts, putt_label = putt_status(bundle, holes)
        if putts:
            putt_rounds += 1
            putts_all.extend(putts)

        tracked = coverage(bundle)
        par = played_par(bundle)
        to_par.append(relative_score(bundle))
        net_to_par.append(net_score(bundle))
        known.append(to_par[-1] is not None)
        print(
            f"  {played_on}  holes={len(holes):2d} strokes={bundle['scorecard'].get('strokes'):3d} "
            f"par={par if par is not None else '-'} "
            f"to_par={format_relative(to_par[-1])} net={format_relative(net_to_par[-1])} "
            f"best={min(strokes)} worst={max(strokes)} penalties={sum(h.get('penalties') or 0 for h in holes)} "
            f"putts={putt_label} untracked={tracked[2]} on {tracked[1]} holes"
        )

    if not per_hole:
        print("nothing to aggregate")
        return

    blowups = sum(1 for s in per_hole if s >= BLOWUP_STROKES)
    print(f"\nstrokes per hole: median {median(per_hole):.1f}, mean {sum(per_hole) / len(per_hole):.2f}")
    print(f"blow-up holes (>={BLOWUP_STROKES} strokes): {blowups}/{len(per_hole)} = {100 * blowups / len(per_hole):.0f}%")
    print(f"penalties: {penalties} over {len(kept)} rounds ({penalties / len(kept):.1f} per round)")
    scored = [v for v in to_par if v is not None]
    if scored:
        print(f"to par: median {format_relative(int(median(scored)))} over {len(scored)}/{len(kept)} rounds "
              f"(best {format_relative(min(scored))}, worst {format_relative(max(scored))})")
        nets = [v for v in net_to_par if v is not None]
        if nets:
            print(f"net to par: median {format_relative(int(median(nets)))} over {len(nets)} rounds "
                  f"(handicap strokes received on the played holes)")
    else:
        print("to par: unavailable (no course pars in these bundles: refetch with garmin_golf_fetch.py)")
    missing = sum(coverage(b)[2] for b in kept)
    print(f"untracked strokes: {missing} over {len(per_hole)} holes ({100 * missing / len(per_hole):.0f}% "
          f"of the score has no shot data)")
    print("distribution:", dict(sorted(stroke_counts.items())))

    if putts_all:
        three_putts = sum(1 for p in putts_all if p >= 3)
        print(
            f"putts: {median(putts_all):.1f} median per hole over {putt_rounds} rounds, "
            f"3-putt rate {100 * three_putts / len(putts_all):.0f}%"
        )
    else:
        print("putts: unavailable (sensor off and no manual entry)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", nargs="?", default="rounds", help="directory of round_*.json")
    parser.add_argument("--min-holes", type=int, default=DEFAULT_MIN_HOLES,
                        help=f"drop rounds with fewer played holes (default: {DEFAULT_MIN_HOLES})")
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
    summarise(bundles, args.min_holes, keep_excluded=args.keep_excluded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
