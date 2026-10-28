"""Per-hole par and relative score, read from the bundle's `course` block.

Garmin sends per-hole par in `courseSnapshots[].holePars`, a digit string
ordered 1..18 on the course. The scorecard's `holes[]` holds the holes actually
played with their `number`, and a BACK_9 round lists numbers 10..18. Pars must
therefore be joined on the hole number, never on the position in the array.

`scorecard.score` is a NET score: strokes - par - handicappedStrokes, where
`handicappedStrokes` is the number of strokes received on the holes actually
played. It is NOT strokes - par - playerHandicap: playerHandicap is the course
handicap for the full course, so on a 9-hole round or a partial round the two
differ by tens of strokes. Every number this module returns is recomputed, and
the handicap strokes are taken from the holes played only.
"""
from __future__ import annotations


def hole_pars(bundle: dict) -> dict[int, int]:
    """{hole number: par} from the bundle, empty when the course block is absent."""
    pars = (bundle.get("course") or {}).get("pars") or {}
    return {int(number): int(par) for number, par in pars.items()}


def played_par(bundle: dict) -> int | None:
    """Total par of the holes actually played, or None when par is unknown."""
    pars = hole_pars(bundle)
    if not pars:
        return None
    holes = [h for h in bundle["scorecard"].get("holes", []) if h.get("strokes") is not None]
    values = [pars[h["number"]] for h in holes if h["number"] in pars]
    if len(values) != len(holes) or not values:
        return None
    return sum(values)


def relative_score(bundle: dict) -> int | None:
    """strokes - par of the played holes. None when par or strokes is unknown."""
    par = played_par(bundle)
    strokes = bundle["scorecard"].get("strokes")
    if par is None or strokes is None:
        return None
    return strokes - par


def handicap_strokes(bundle: dict) -> int:
    """Handicap strokes received on the played holes.

    Garmin gives the round total in `handicappedStrokes` but nothing per hole,
    so this is only exact for the round it belongs to. A round whose
    `handicappedStrokes` is missing gets 0, and the caller must not treat that
    as a real net score.
    """
    return int(bundle["scorecard"].get("handicappedStrokes") or 0)


def net_score(bundle: dict) -> int | None:
    """strokes - par of the played holes - handicap strokes received on them."""
    relative = relative_score(bundle)
    if relative is None:
        return None
    return relative - handicap_strokes(bundle)


def format_relative(value: int | None) -> str:
    """+12 / E / -3, or a dash when the number is unknown."""
    if value is None:
        return "-"
    if value == 0:
        return "E"
    return f"{value:+d}"
