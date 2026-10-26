#!/usr/bin/env python3
"""Round debrief from the bundles written by garmin_golf_fetch.py.

Focuses on the numbers that actually decide a score: strokes per hole
distribution, blow-up holes, penalties, and putts - with the traps handled:

  * per-hole par is always null in Garmin data, so scoring is reported in
    strokes, never as "over par";
  * when the putter sensor was off, Garmin writes a constant putts=2 on every
    hole: those values are detected and dropped instead of being averaged;
  * practice and abandoned rounds are filtered out before any aggregate.

Usage:
    python round_report.py rounds/
    python round_report.py rounds/ --min-holes 9
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from statistics import median

DEFAULT_MIN_HOLES = 9
MIN_STROKES_9 = 35
MIN_STROKES_18 = 60
BLOWUP_STROKES = 7


def load_bundles(directory: str) -> list[dict]:
    bundles = []
    for name in sorted(os.listdir(directory)):
        if name.startswith("round_") and name.endswith(".json"):
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                bundles.append(json.load(handle))
    return bundles


def played_holes(bundle: dict) -> list[dict]:
    """Played holes only: unplayed ones are padded with strokes=None."""
    return [h for h in bundle["scorecard"].get("holes", []) if h.get("strokes") is not None]


def is_meaningful(bundle: dict, min_holes: int) -> bool:
    holes = played_holes(bundle)
    strokes = bundle["scorecard"].get("strokes") or 0
    if len(holes) < min_holes:
        return False
    if len(holes) >= 18:
        return strokes >= MIN_STROKES_18
    return strokes >= MIN_STROKES_9


def usable_putts(bundle: dict, holes: list[dict]) -> list[int] | None:
    """Return per-hole putts, or None when Garmin filled them with a constant."""
    putts = [h.get("putts") for h in holes if h.get("putts") is not None]
    if not putts:
        return None
    # Sensor off: Garmin writes 2 on every hole. Manual entry always varies.
    if len(set(putts)) == 1:
        return None
    return putts


def summarise(bundles: list[dict], min_holes: int) -> None:
    kept = [b for b in bundles if is_meaningful(b, min_holes)]
    dropped = len(bundles) - len(kept)
    print(f"{len(kept)} rounds kept, {dropped} dropped as partial/practice")

    stroke_counts: Counter[int] = Counter()
    per_hole: list[int] = []
    penalties = 0
    putts_all: list[int] = []
    putt_rounds = 0

    for bundle in kept:
        holes = played_holes(bundle)
        played_on = bundle["scorecard"]["startTime"][:10]
        strokes = [h["strokes"] for h in holes]
        penalties += sum(h.get("penalties") or 0 for h in holes)
        stroke_counts.update(strokes)
        per_hole.extend(strokes)

        putts = usable_putts(bundle, holes)
        if putts:
            putt_rounds += 1
            putts_all.extend(putts)

        print(
            f"  {played_on}  holes={len(holes):2d} strokes={bundle['scorecard'].get('strokes'):3d} "
            f"best={min(strokes)} worst={max(strokes)} penalties={sum(h.get('penalties') or 0 for h in holes)}"
        )

    if not per_hole:
        print("nothing to aggregate")
        return

    blowups = sum(1 for s in per_hole if s >= BLOWUP_STROKES)
    print(f"\nstrokes per hole: median {median(per_hole):.1f}, mean {sum(per_hole) / len(per_hole):.2f}")
    print(f"blow-up holes (>={BLOWUP_STROKES} strokes): {blowups}/{len(per_hole)} = {100 * blowups / len(per_hole):.0f}%")
    print(f"penalties: {penalties} over {len(kept)} rounds ({penalties / len(kept):.1f} per round)")
    print("distribution:", dict(sorted(stroke_counts.items())))

    if putts_all:
        three_putts = sum(1 for p in putts_all if p >= 3)
        print(
            f"putts: {median(putts_all):.1f} median per hole over {putt_rounds} rounds, "
            f"3-putt rate {100 * three_putts / len(putts_all):.0f}%"
        )
    else:
        print("putts: unavailable (sensor off and no manual entry)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", nargs="?", default="rounds", help="directory of round_*.json")
    parser.add_argument("--min-holes", type=int, default=DEFAULT_MIN_HOLES,
                        help=f"drop rounds with fewer played holes (default: {DEFAULT_MIN_HOLES})")
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"no such directory: {args.directory}", file=sys.stderr)
        return 2
    bundles = load_bundles(args.directory)
    if not bundles:
        print(f"no round_*.json in {args.directory}", file=sys.stderr)
        return 1
    summarise(bundles, args.min_holes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
