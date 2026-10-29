"""Bridge Garmin round bundles to the shot/distance schema both reports consume.

The bundles written by garmin_golf_fetch.py are a cheap merge of two API
endpoints: `scorecard` (per-hole totals, manually entered putts) and `shots`
(watch GPS points, a fraction of the swings played). Neither is complete, and
they do not add up:

  * a hole with 7 strokes can carry 5 tracked shots and 1 putt;
  * a tracked "PUTT" shot may already be part of the `putts` count;
  * a hole can have strokes recorded and no tracked shot at all.

Nothing in the Garmin payload says which tracked shots are missing, so this
module does NOT invent them. It only exposes the gap so the reports can print
it instead of hiding it.
"""
from __future__ import annotations


def hole_shots(bundle: dict) -> dict[int, list[dict]]:
    """{hole number: tracked shots}, keys normalised to int."""
    out: dict[int, list[dict]] = {}
    for key, shots in (bundle.get("shots") or {}).items():
        out[int(key)] = shots
    return out


def non_putt_count(shots: list[dict]) -> int:
    """Tracked shots that are not putts; putts are counted from the scorecard."""
    return sum(1 for s in shots if s.get("shotType") != "PUTT")


def hole_discrepancy(hole: dict, shots: list[dict]) -> int:
    """strokes - (non-putt tracked shots + putts). Non-zero means data is missing."""
    strokes = hole.get("strokes") or 0
    putts = hole.get("putts") or 0
    return strokes - (non_putt_count(shots) + putts)


def coverage(bundle: dict) -> tuple[int, int, int]:
    """(holes, holes with a discrepancy, total positive gap in strokes).

    The positive gap is the number of strokes the watch never recorded: the
    reports can never claim "we tracked every shot".
    """
    holes = [h for h in bundle["scorecard"].get("holes", []) if h.get("strokes") is not None]
    shots = hole_shots(bundle)
    gaps = [hole_discrepancy(h, shots.get(h["number"], [])) for h in holes]
    off = sum(1 for g in gaps if g != 0)
    missing = sum(g for g in gaps if g > 0)
    return len(holes), off, missing
