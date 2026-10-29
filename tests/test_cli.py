"""The `gga` dispatcher: one entry point, three commands."""
from __future__ import annotations

import pytest

from garmin_golf_analytics import cli


def test_help_without_arguments_returns_error(capsys):
    assert cli.main([]) == 2
    assert "usage: cli {fetch,clubs,rounds}" in capsys.readouterr().out


def test_explicit_help_returns_success(capsys):
    assert cli.main(["--help"]) == 0
    assert "rounds  round debrief" in capsys.readouterr().out


def test_unknown_command_is_rejected(capsys):
    assert cli.main(["bogus"]) == 2
    assert "unknown command: bogus" in capsys.readouterr().err


def test_dispatch_forwards_remaining_argv(monkeypatch):
    seen: list[list[str] | None] = []

    def fake_main(argv=None):
        seen.append(argv)
        return 0

    monkeypatch.setattr("garmin_golf_analytics.club_report.main", fake_main)
    assert cli.main(["clubs", "rounds/", "--lie", "TeeBox"]) == 0
    # main() re-reads sys.argv, which now holds the forwarded arguments
    assert seen == [None]


def test_dispatch_rewrites_sys_argv(monkeypatch):
    import sys

    called: list[str] = []

    def fake_main(argv=None):
        called.extend(sys.argv)
        return 0

    monkeypatch.setattr("garmin_golf_analytics.round_report.main", fake_main)
    cli.main(["rounds", "rounds/", "--min-holes", "18"])
    assert called == ["cli rounds", "rounds/", "--min-holes", "18"]
