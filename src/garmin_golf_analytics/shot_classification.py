"""What a shot actually was, and which shots belong in a club table.

Garmin stamps every tracked shot with a `shotType` and a starting lie. Neither
is trustworthy on its own: `shotType` is UNKNOWN for a third of the shots, and
`lie == "TeeBox"` means "first shot of this hole", not "hit from the tee". Those
two facts decide every distance this package prints, so they live here, in one
place, rather than being re-derived by each report.

Nothing in this module prints.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

# The putter is a real club off the green on dry, fast turf: a putt hit from the
# green is a stroke of the short game, a putt hit from anywhere else is an
# approach and deserves its own row. Garmin gives both the same shotType.
PUTTER = "Putter"
# A shot this short is a top, a duff or a mis-hit: it never describes the club.
MISHIT_METERS = 60
# A shot starting this close to the green and finishing on it is a chip, not an
# approach, whatever Garmin called it: 14 of the Gap Wedge's UNKNOWN shots ran
# 10 to 45 m from the fringe onto the green.
CHIP_RANGE_METERS = 50
LIE_ORDER = ("TeeBox", "Fairway", "Rough", "Bunker", "Green", "Recovery")
GOOD_LIES = ("Fairway", "Green")

# Garmin labels a shot TEE, APPROACH, CHIP, LAYUP, PUTT or UNKNOWN. UNKNOWN is
# Garmin having no idea, not a shot type of its own: it is a large share of the
# tracked shots and dropping it silently shrinks every sample. Only the putts
# are refused here; everything else is labelled from the lie and the shot's
# position in the hole.
SHOT_TYPE_LABELS = {
    "TEE": "Tee",
    "APPROACH": "Approach",
    "CHIP": "Chip",
    "LAYUP": "Layup",
    "PITCH": "Pitch",
    "RECOVERY": "Recovery",
}
UNKNOWN_LABEL = "Unclassified"
# A par 4 or 5 opened on TeeBox with a club short of a driver is the player
# laying up, not driving.
PAR_THAT_ALLOWS_A_LAYUP = (4, 5)
LONG_CLUBS = ("Driver", "1 Wood", "3 Wood", "2 Wood", "4 Wood")
LAYUP_ON_TEE = "Layup (tee)"
SHORT_GAME_SHOT_TYPES = ("CHIP", "PITCH", "RECOVERY")
MISHIT_LABEL = "Mishit"
# The order a player thinks about a hole: off the tee, then the second shot,
# then the short game, with whatever could not be classified last.
KIND_ORDER = ("Tee", LAYUP_ON_TEE, "Approach", "Layup", "Pitch", "Chip", "Recovery", "Putt", UNKNOWN_LABEL)


def percentile(values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile on an unsorted list."""
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


def is_usable_shot(shot: dict) -> bool:
    """Whether a shot may enter a club table at all.

    `clubId == 0` means the watch could not identify the club: those shots carry
    an UNKNOWN shotType and must never be shown as a "club". No name means an
    unmapped clubTypeId: an id in a club table is noise and compares to nothing.
    """
    if not shot.get("clubId") or shot.get("excludeFromStats"):
        return False
    return bool(shot.get("clubName"))


def is_short_game_putt(shot: dict) -> bool:
    """A putter stroke played from the green: short game, not a club distance."""
    club = shot.get("clubName")
    shot_lie = (shot.get("startLoc") or {}).get("lie") or "Unknown"
    return club == PUTTER and shot_lie == "Green"


def puts_off_green(shot: dict) -> bool:
    """A putter stroke that never reached the green is not an approach either."""
    return shot.get("clubName") == PUTTER and (shot.get("endLoc") or {}).get("lie") != "Green"


def shot_kind(shot: dict, club: str, hole_par: int | None) -> str:
    """What the shot actually was, from Garmin's label and the lie.

    Garmin's own `shotType` is used when it is specific. When it says UNKNOWN,
    the lie, the shot's position in the hole and the distance decide:
      * on the green                             -> Putt
      * first shot of a par 4 or 5, long club    -> Tee
      * first shot of a par 4 or 5, short club   -> Layup (tee)
      * first shot of a par 3                    -> Tee
      * finishing on the green from under CHIP_RANGE_METERS -> Chip
      * anything else                            -> Unclassified
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
        if not is_usable_shot(shot):
            continue
        shot_lie = (shot.get("startLoc") or {}).get("lie") or "Unknown"
        end_lie = (shot.get("endLoc") or {}).get("lie") or "Unknown"
        if shot.get("shotType") == "PUTT" and shot_lie == "Green":
            continue
        club = shot.get("clubName")
        # Keep putts played off the green: they are approaches with a flat club.
        # A putt that never reaches the green is not an approach either.
        if is_short_game_putt(shot) or puts_off_green(shot):
            continue
        if club == PUTTER:
            club = "Putter (approach)"
        if meters is None or meters < min_meters:
            continue
        if lie and shot_lie != lie:
            continue
        grouped[(club, shot_lie)].append((float(meters), end_lie))
    return grouped


def collect_by_kind(shots: Iterable[dict], min_meters: float,
                    pars: dict | None = None) -> dict[tuple, list[float]]:
    """Same rules, but grouped by (club, shot kind) so the profile is visible.

    A median computed over tees, approaches and chips of one club describes no
    shot anybody plays. `pars` maps a hole number to its par; without it the
    first shot of a par 4 cannot be told apart from a layup.
    """
    grouped: dict[tuple, list[float]] = defaultdict(list)
    for shot in shots:
        meters = shot.get("meters")
        if not is_usable_shot(shot):
            continue
        if is_short_game_putt(shot) or puts_off_green(shot):
            continue
        club = str(shot["clubName"])
        if meters is None or meters < min_meters:
            continue
        hole_par = shot.get("par")
        if hole_par is None:
            hole_par = (pars or {}).get(str(shot.get("hole")))
        kind = shot_kind(shot, club, hole_par)
        grouped[(club, kind)].append(float(meters))
    return grouped


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
