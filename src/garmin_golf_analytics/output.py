"""Machine-readable output: one flat JSON record per row of a report.

The tables the CLIs print are built for a person reading a terminal. Anything
longer-lived than a glance (a trend line, a spreadsheet, a post in another
tool) needs the same numbers with the labels attached, so a caller never has
to parse columns of padded text and re-guess which window a figure came from.

Every record is a flat dict of scalars: `None` stays JSON `null` rather than
being replaced by a zero, because a missing measurement and a measured zero are
different facts. Units are carried by the key name (`meters`, `percent`,
`per_hole`, `per_round`) so a consumer does not have to know the report.
"""
from __future__ import annotations

import csv
import json
import sys
from typing import Any, Iterable


def _clean(value: Any) -> Any:
    """Round floats to a readable precision; leave ints, str and None alone."""
    if isinstance(value, float) and value == value and abs(value) != float("inf"):
        return round(value, 4)
    return value


def write(records: Iterable[dict], fmt: str, stream=None) -> None:
    """Write `records` as JSON (a list) or CSV (one line per record)."""
    rows = [{key: _clean(value) for key, value in record.items()} for record in records]
    out = stream or sys.stdout
    if fmt == "json":
        json.dump(rows, out, ensure_ascii=False, indent=2)
        out.write("\n")
        return
    if fmt == "csv":
        if not rows:
            return
        # Field order comes from the first record: every record of one report is
        # built from the same row, so the columns line up by construction.
        writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return
    raise ValueError(f"unknown format: {fmt!r}")
