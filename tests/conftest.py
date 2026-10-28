"""Fixtures: build round bundles shaped like the ones garmin_golf_fetch.py writes."""
from __future__ import annotations

import json

import pytest


def hole(number: int, strokes: int | None, putts: int | None = 2, penalties: int = 0) -> dict:
    return {"number": number, "strokes": strokes, "putts": putts, "penalties": penalties}


def shot(club: str, meters: float, lie: str = "Fairway", club_id: int = 100,
         order: int = 1, exclude: bool = False) -> dict:
    return {
        "clubId": club_id,
        "clubName": club,
        "meters": meters,
        "shotOrder": order,
        "startLoc": {"lie": lie},
        "excludeFromStats": exclude,
    }


def bundle(date: str = "2026-09-01", course: int = 25184, holes: list | None = None,
           sensor: bool = False, exclude: bool = False, strokes: int | None = None,
           shots: dict | None = None) -> dict:
    if holes is None:
        holes = [hole(n, 5) for n in range(1, 10)]
    total = strokes if strokes is not None else sum(h["strokes"] or 0 for h in holes)
    scorecard = {
        "startTime": f"{date} 08:00:00",
        "courseGlobalId": course,
        "courseSnapshotId": 1,
        "strokes": total,
        "score": 0,
        "playerHandicap": 0,
        "sensorOnPutter": sensor,
        "excludeFromStats": exclude,
        "holes": holes,
    }
    return {"scorecard": scorecard, "shots": shots or {str(h["number"]): [] for h in holes},
            "playedHoles": sum(1 for h in holes if h["strokes"] is not None)}


@pytest.fixture
def rounds_dir(tmp_path):
    """Write bundles to a temp directory and return its path."""
    def _write(*bundles: dict) -> str:
        for index, data in enumerate(bundles):
            date = data["scorecard"]["startTime"][:10]
            course = data["scorecard"].get("courseGlobalId", 0)
            path = tmp_path / f"round_{date}_{course}{index}.json"
            path.write_text(json.dumps(data), encoding="utf-8")
        return str(tmp_path)
    return _write
