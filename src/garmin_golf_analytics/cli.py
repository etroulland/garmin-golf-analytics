"""Console entry points for the garmin-golf-analytics commands.

Each command is a thin wrapper around the ``main(argv)`` of one module, so the
CLIs stay testable and nothing imports garminconnect unless you actually fetch.
"""
from __future__ import annotations

import sys


def fetch() -> int:
    from .garmin_golf_fetch import main

    return main()


def clubs() -> int:
    from .club_report import main

    return main()


def rounds() -> int:
    from .round_report import main

    return main()


def compare() -> int:
    from .compare_report import main

    return main()


def main(argv: list[str] | None = None) -> int:
    """Dispatch on the first argument: ``cli fetch|clubs|rounds|compare ...``."""
    args = list(sys.argv[1:] if argv is None else argv)
    commands = {"fetch": fetch, "clubs": clubs, "rounds": rounds, "compare": compare}
    if not args or args[0] in ("-h", "--help"):
        print("usage: cli {fetch,clubs,rounds,compare} [options]\n"
              "  fetch    pull rounds from Garmin Connect\n"
              "  clubs    per-club distances, split by lie\n"
              "  rounds   round debrief (score, penalties, putting)\n"
              "  compare  two date windows side by side")
        return 0 if args else 2
    command = commands.get(args[0])
    if command is None:
        print(f"unknown command: {args[0]} (expected fetch, clubs, rounds or compare)", file=sys.stderr)
        return 2
    sys.argv = [f"cli {args[0]}", *args[1:]]
    return command()
