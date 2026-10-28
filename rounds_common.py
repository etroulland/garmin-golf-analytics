#!/usr/bin/env python3
"""Round selection shared by club_report.py and round_report.py.

Both reports must look at the same rounds, otherwise the distance table and the
score table describe two different samples. Every rule that decides whether a
round counts lives here, once.

A round is dropped for exactly one reason, and the reason is reported:
  * excluded  - Garmin's own `excludeFromStats` flag (practice, league, etc.)
  * partial   - fewer than --min-holes played holes (unplayed holes are padded
                with strokes=None)
  * practice  - implausibly few strokes for the holes played (range/practice)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

MIN_STROKES_9 = 35
MIN_STROKES_18 = 60


@dataclass
class Selection:
    kept: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    partial: list[dict[str, Any]] = field(default_factory=list)
    practice: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dropped(self) -> int:
        return len(self.excluded) + len(self.partial) + len(self.practice)

    def describe(self) -> str:
        parts = [f"{len(self.kept)} rounds kept"]
        if self.excluded:
            parts.append(f"{len(self.excluded)} excluded by Garmin")
        if self.partial:
            parts.append(f"{len(self.partial)} partial")
        if self.practice:
            parts.append(f"{len(self.practice)} practice")
        return ", ".join(parts)


def load_bundles(directory: str) -> list[dict[str, Any]]:
    bundles = []
    for name in sorted(os.listdir(directory)):
        if not (name.startswith("round_") and name.endswith(".json")):
            continue
        with open(os.path.join(directory, name), encoding="utf-8") as handle:
            bundles.append(json.load(handle))
    return bundles


def played_holes(bundle: dict) -> list[dict]:
    """Played holes only: unplayed ones are padded with strokes=None."""
    return [h for h in bundle["scorecard"].get("holes", []) if h.get("strokes") is not None]


def short_reason(bundle: dict, min_holes: int) -> str | None:
    """Why this round does not count, or None when it does."""
    if bundle["scorecard"].get("excludeFromStats"):
        return "excluded"
    holes = played_holes(bundle)
    if len(holes) < min_holes:
        return "partial"
    strokes = bundle["scorecard"].get("strokes") or 0
    floor = MIN_STROKES_18 if len(holes) >= 18 else MIN_STROKES_9
    return None if strokes >= floor else "practice"


def select(bundles: list[dict], min_holes: int, keep_excluded: bool = False) -> Selection:
    """Split rounds into kept and the three drop reasons."""
    selection = Selection()
    for bundle in bundles:
        reason = short_reason(bundle, min_holes)
        if reason == "excluded" and keep_excluded:
            reason = None
        if reason is None:
            selection.kept.append(bundle)
        else:
            getattr(selection, reason).append(bundle)
    return selection
