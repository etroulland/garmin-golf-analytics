#!/usr/bin/env python3
"""Compare two date windows: is the player better now than before?

A single number per period is a trap. Strokes over par cannot be compared across
periods that played different holes (a 9-hole +16 against an 18-hole +26 says
nothing), so every figure here is per hole or a rate, and the sample size of
each side is printed next to it. The deltas are signed from A to B, and a delta
computed on fewer rounds than `--min-sample` is flagged rather than trusted.

Periods are explicit dates (`2026-01-01:2026-06-30`), never calendar years:
21 rounds spread over 12 months do not survive a monthly comparison.

Usage:
    python compare_report.py rounds/ --period 2025-01-01:2025-12-31 --period 2026-01-01:2026-12-31
    python compare_report.py rounds/ --period 2026-01-01:2026-06-30 --period 2026-07-01:2026-12-31
    python compare_report.py rounds/ --period 2025 --period 2026    # whole calendar years

Exactly two --period values are accepted, in the order they are printed.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from datetime import date
from statistics import median

from . import output
from .club_report import (
    DEFAULT_MIN_SHOTS,
    DISTANCE_LABEL,
    MISHIT_METERS,
    bundle_pars,
    collect_by_kind,
    iter_shots,
    percentile,
)
from .round_report import BLOWUP_STROKES, putt_status
from .rounds_common import load_bundles, played_holes, select
from .scoring import net_score, relative_score

DESCRIPTION = "Compare two date windows: is the player better now than before?"
DEFAULT_MIN_HOLES = 9
# Below this many rounds in either window, the delta is displayed but flagged:
# it is the difference of two medians, and medians of small samples move a lot.
DEFAULT_MIN_SAMPLE = 5


def parse_period(text: str) -> tuple[date, date]:
    """`YYYY-MM-DD:YYYY-MM-DD`, or `YYYY` for a whole calendar year."""
    raw = text.strip()
    if len(raw) == 4 and raw.isdigit():
        year = int(raw)
        return date(year, 1, 1), date(year, 12, 31)
    if ":" not in raw:
        raise ValueError(f"expected START:END or YYYY, got {text!r}")
    start_text, end_text = (part.strip() for part in raw.split(":", 1))
    start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    return start, end


def round_date(bundle: dict) -> date:
    """The date the round was played, taken from Garmin's own start time."""
    return date.fromisoformat(bundle["scorecard"]["startTime"][:10])


def in_period(bundle: dict, period: tuple[date, date]) -> bool:
    played_on = round_date(bundle)
    return period[0] <= played_on <= period[1]


def profile(bundles: list[dict]) -> dict:
    """Per-hole figures for one set of already-selected rounds.

    Every value is a per-hole mean/median or a rate, so two windows with
    different hole counts stay comparable. `None` means the data does not allow
    the figure (no putts recorded, no course par), never a zero standing in for
    a missing measurement.
    """
    holes_played = 0
    strokes_per_hole: list[int] = []
    to_par_per_hole: list[float] = []
    net_per_hole: list[float] = []
    blowups = 0
    penalties = 0
    putts: list[int] = []
    putt_rounds = 0

    for bundle in bundles:
        holes = played_holes(bundle)
        if not holes:
            continue
        holes_played += len(holes)
        strokes = [h["strokes"] for h in holes]
        strokes_per_hole.extend(strokes)
        blowups += sum(1 for value in strokes if value >= BLOWUP_STROKES)
        penalties += sum(h.get("penalties") or 0 for h in holes)

        relative = relative_score(bundle)
        if relative is not None:
            to_par_per_hole.append(relative / len(holes))
        net = net_score(bundle)
        if net is not None:
            net_per_hole.append(net / len(holes))

        round_putts, _ = putt_status(bundle, holes)
        if round_putts:
            putt_rounds += 1
            putts.extend(round_putts)

    if not strokes_per_hole:
        return {"rounds": 0, "holes": 0}

    three_putts = sum(1 for value in putts if value >= 3)
    return {
        "rounds": len(bundles),
        "holes": holes_played,
        "strokes_per_hole": median(strokes_per_hole),
        "to_par_per_hole": median(to_par_per_hole) if to_par_per_hole else None,
        "net_per_hole": median(net_per_hole) if net_per_hole else None,
        "blowup_rate": 100 * blowups / len(strokes_per_hole),
        "penalties_per_round": penalties / len(bundles) if bundles else None,
        "putt_rate_3": 100 * three_putts / len(putts) if putts else None,
        "putt_rounds": putt_rounds,
    }


def club_profile(bundles: list[dict], min_meters: float) -> list[dict]:
    """Per-club, per-shot-kind distance profile of one selection of rounds.

    Same shot rules as club_report.py (`collect_by_kind`: putts on the green
    out, putts ending on the green kept as "Putter (approach)", mishit floor per
    club), so a distance here is the distance gga-clubs prints for that row.

    One record per (club, kind) with at least one usable shot. `p75` and `max`
    are the same percentiles the club table shows, not guesses.
    """
    grouped = collect_by_kind(iter_shots(bundles), min_meters, bundle_pars(bundles))
    records = []
    for (club, kind), distances in sorted(grouped.items()):
        median_distance = percentile(distances, 0.5)
        # The club's own floor: a wedge never plays 60 m, a driver never plays 12.
        floor = min(MISHIT_METERS, median_distance * 0.5)
        played = [distance for distance in distances if distance >= floor]
        if not played:
            continue
        records.append({
            "club": club,
            "shot_kind": kind,
            "n": len(played),
            "median_m": round(percentile(played, 0.5), 1),
            "p75_m": round(percentile(played, 0.75), 1),
            "max_m": round(max(played), 1),
            "mishits": len(distances) - len(played),
        })
    return records


def club_compare(bundles: list[dict], periods: tuple[tuple[date, date], ...],
                 min_holes: int, min_meters: float, min_shots: int,
                 keep_excluded: bool = False) -> tuple[list[dict], list[str]]:
    """Two windows side by side, one row per club and shot kind.

    Returns (records, lines_to_print). A club the player hit in only one window
    is still a row, with `None` on the other side: pretending it does not exist
    would hide exactly the change a comparison is looking for. A delta is
    withheld, not computed, when either side has fewer than `min_shots` usable
    shots, and each side's n is in the row so the caller can see why.
    """
    titles = [f"{period[0]}..{period[1]}" for period in periods]
    lines = []
    sides: list[dict[tuple[str, str], dict]] = []
    for period in periods:
        window = [bundle for bundle in bundles if in_period(bundle, period)]
        selection = select(window, min_holes, keep_excluded=keep_excluded)
        lines.append(f"{period[0]} .. {period[1]}: {selection.describe()}")
        sides.append({(record["club"], record["shot_kind"]): record
                      for record in club_profile(selection.kept, min_meters)})

    left, right = sides
    keys = sorted(set(left) | set(right), key=lambda key: (-(right.get(key) or left[key])["median_m"], key))
    records: list[dict] = []
    for club, kind in keys:
        first, second = left.get((club, kind)), right.get((club, kind))
        first_median = first["median_m"] if first else None
        second_median = second["median_m"] if second else None
        thin = (first is None or second is None
                or first["n"] < min_shots or second["n"] < min_shots)
        records.append({
            "club": club,
            "shot_kind": kind,
            "n_a": first["n"] if first else 0,
            "median_a_m": first_median,
            "n_b": second["n"] if second else 0,
            "median_b_m": second_median,
            "delta_m": None if thin else round((second_median or 0) - (first_median or 0), 1),
            "low_confidence": thin,
        })

    if not records:
        return records, lines

    _title_a, _title_b = (title[:16] for title in titles)
    lines.append("")
    lines.append(f"{'club':22} {'shot':12} {'n a':>4} {'med a':>6} {'n b':>4} {'med b':>6} {'delta':>7}")
    lines.append("-" * 66)
    for record in records:
        flag = "  (low n)" if record["low_confidence"] else ""
        lines.append(
            f"{record['club'][:22]:22} {record['shot_kind'][:12]:12} "
            f"{record['n_a']:4d} {_value(record['median_a_m'], 0):>6} "
            f"{record['n_b']:4d} {_value(record['median_b_m'], 0):>6} "
            f"{_signed(record['delta_m'], 1) if record['delta_m'] is not None else '-':>7}{flag}"
        )
    lines.append("")
    lines.append(f"Distances are {DISTANCE_LABEL}. A delta needs at least "
                 f"{min_shots} usable shots on each side; it is withheld, not guessed.")
    return records, lines


def _signed(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "     -"
    return f"{value:+.{decimals}f}"


def _value(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:.{decimals}f}"


def _delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return after - before


def player_records(bundles: list[dict], periods: tuple[tuple[date, date], ...],
                   min_holes: int, keep_excluded: bool = False,
                   min_sample: int = DEFAULT_MIN_SAMPLE) -> list[dict] | None:
    """One record per metric, both windows and the signed delta, or None if empty.

    Same figures `compare()` prints, so `--json` and the table can never drift
    apart. `delta` is None when either side lacks the measurement or when a
    window is too thin to carry a difference at all.
    """
    sides: list[dict] = []
    for period in periods:
        window = [bundle for bundle in bundles if in_period(bundle, period)]
        sides.append(profile(select(window, min_holes, keep_excluded=keep_excluded).kept))
    if not all(side["rounds"] for side in sides):
        return None

    left, right = sides
    thin = left["rounds"] < min_sample or right["rounds"] < min_sample
    title_a, title_b = (f"{period[0]}..{period[1]}" for period in periods)
    records = [
        {"metric": "rounds", "a": left["rounds"], "b": right["rounds"], "delta": None},
        {"metric": "holes_played", "a": left["holes"], "b": right["holes"], "delta": None},
    ]
    for metric, key, decimals in (
        ("strokes_per_hole", "strokes_per_hole", 2),
        ("over_par_per_hole", "to_par_per_hole", 2),
        ("net_to_par_per_hole", "net_per_hole", 2),
        ("blowup_holes_percent", "blowup_rate", 1),
        ("penalties_per_round", "penalties_per_round", 2),
        ("three_putts_percent", "putt_rate_3", 1),
    ):
        first, second = left.get(key), right.get(key)
        records.append({
            "metric": metric,
            "a": first,
            "b": second,
            "delta": None if thin else _round(_delta(first, second), decimals),
        })
    for record in records:
        record["period_a"] = title_a
        record["period_b"] = title_b
        record["low_confidence"] = thin
    return records


def _round(value: float | None, decimals: int) -> float | None:
    return None if value is None else round(value, decimals)


def compare(bundles: list[dict], periods: tuple[tuple[date, date], ...],
            min_holes: int, keep_excluded: bool = False,
            min_sample: int = DEFAULT_MIN_SAMPLE) -> int:
    """Print both windows side by side and the signed delta, A then B.

    Returns 0 when both windows hold rounds, 1 when one of them is empty: a
    comparison against nothing is not a comparison.
    """
    sides: list[dict] = []
    for period in periods:
        window = [bundle for bundle in bundles if in_period(bundle, period)]
        selection = select(window, min_holes, keep_excluded=keep_excluded)
        sides.append(profile(selection.kept))
        print(f"{period[0]} .. {period[1]}: {selection.describe()}")

    if not all(side["rounds"] for side in sides):
        empty = [f"{period[0]}..{period[1]}" for period, side in zip(periods, sides, strict=True)
                 if not side["rounds"]]
        print(f"nothing to compare in: {', '.join(empty)}", file=sys.stderr)
        return 1

    left, right = sides
    rows = [
        ("rounds", "rounds", 0, _value, None),
        ("holes played", "holes", 0, _value, None),
        ("strokes per hole", "strokes_per_hole", 2, _value, True),
        ("over par per hole", "to_par_per_hole", 2, _signed, True),
        ("net to par per hole", "net_per_hole", 2, _signed, True),
        ("blow-up holes %", "blowup_rate", 1, _value, True),
        ("penalties per round", "penalties_per_round", 2, _value, True),
        ("3-putts %", "putt_rate_3", 1, _value, True),
    ]
    thin = left["rounds"] < min_sample or right["rounds"] < min_sample

    title_a, title_b = (f"{period[0]}..{period[1]}"[:16] for period in periods)
    print(f"\n{'metric':22} {title_a:>16} {title_b:>16} {'delta':>9}")
    print("-" * 66)
    for label, key, decimals, formatter, comparable in rows:
        first, second = left.get(key), right.get(key)
        print(f"{label:22} {formatter(first, decimals) if first is not None else '-':>16} "
              f"{formatter(second, decimals) if second is not None else '-':>16} "
              f"{_signed(_delta(first, second), decimals) if comparable else '':>9}")

    print("\nAll figures are per hole or a rate: windows with different hole counts stay comparable.")
    if thin:
        print(f"Low confidence: fewer than {min_sample} rounds on one side, the deltas are noise.")
    if left["putt_rounds"] < left["rounds"] or right["putt_rounds"] < right["rounds"]:
        print(f"Putt figures cover {left['putt_rounds']}/{left['rounds']} and "
              f"{right['putt_rounds']}/{right['rounds']} rounds with usable data only.")
    missing_par = [period for period, side in zip(periods, sides, strict=True)
                   if side.get("to_par_per_hole") is None]
    if missing_par:
        print("Over par unavailable for: " + ", ".join(f"{p[0]}..{p[1]}" for p in missing_par)
              + " (no course pars in those bundles: refetch)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("directory", nargs="?", default="rounds",
                        help="directory of round_*.json (default: rounds)")
    parser.add_argument("--period", action="append", metavar="START:END", required=True,
                        help="YYYY-MM-DD:YYYY-MM-DD or YYYY; give it twice, first window then second")
    parser.add_argument("--min-holes", type=int, default=DEFAULT_MIN_HOLES,
                        help=f"drop rounds with fewer played holes (default: {DEFAULT_MIN_HOLES})")
    parser.add_argument("--min-sample", type=int, default=DEFAULT_MIN_SAMPLE,
                        help=f"flag the comparison below this many rounds per window "
                             f"(default: {DEFAULT_MIN_SAMPLE})")
    parser.add_argument("--keep-excluded", action="store_true",
                        help="also use rounds Garmin flagged excludeFromStats")
    parser.add_argument("--by", choices=("player", "club"), default="player",
                        help="what to compare: the player's per-hole scoring or each club's "
                             "distances (default: player)")
    parser.add_argument("--min-shots", type=int, default=DEFAULT_MIN_SHOTS,
                        help=f"with --by club, withhold a distance delta under this many usable "
                             f"shots on either side (default: {DEFAULT_MIN_SHOTS})")
    parser.add_argument("--min-meters", type=float, default=0.0,
                        help="with --by club, drop shots below this total distance (default: none)")
    parser.add_argument("--format", choices=("text", "json", "csv"), default="text",
                        help="text for a person, json or csv for anything that will outlive the "
                             "glance (default: text); json/csv go to stdout alone")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.directory):
        print(f"no such directory: {args.directory}", file=sys.stderr)
        return 2
    try:
        periods = tuple(parse_period(text) for text in args.period)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if len(periods) != 2:
        print(f"two --period values needed, got {len(periods)}", file=sys.stderr)
        return 2
    bundles = load_bundles(args.directory)
    if not bundles:
        print(f"no round_*.json in {args.directory}", file=sys.stderr)
        return 1

    if args.by == "club" and args.format != "text":
        records, _ = club_compare(bundles, periods, args.min_holes, args.min_meters,
                                  args.min_shots, keep_excluded=args.keep_excluded)
        if not records:
            print("no tracked shot in either window", file=sys.stderr)
            return 1
        output.write(records, args.format)
        return 0
    if args.by == "club":
        records, lines = club_compare(bundles, periods, args.min_holes, args.min_meters,
                                      args.min_shots, keep_excluded=args.keep_excluded)
        for line in lines:
            print(line)
        if not records:
            print("no tracked shot in either window", file=sys.stderr)
            return 1
        return 0

    compared = player_records(bundles, periods, args.min_holes,
                              keep_excluded=args.keep_excluded, min_sample=args.min_sample)
    if compared is None:
        print("nothing to compare in one of the two windows", file=sys.stderr)
        return 1
    if args.format != "text":
        output.write(compared, args.format)
        return 0
    return compare(bundles, periods, args.min_holes, keep_excluded=args.keep_excluded,
                   min_sample=args.min_sample)


def entry_point(argv: list[str] | None = None) -> int:
    """Console-script wrapper: see club_report.entry_point for why."""
    try:
        return main(argv)
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError, io.UnsupportedOperation):
            pass
        return 0


if __name__ == "__main__":
    sys.exit(entry_point())
