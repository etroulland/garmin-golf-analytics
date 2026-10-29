"""The console scripts must behave like Unix tools when their reader goes away.

`gga-clubs rounds/ | head` used to finish with a BrokenPipeError traceback once
the 10th line closed the pipe. Piping into `head`, `less` or `grep -m1` is the
normal way to read this output, so the traceback was the common case, not an
edge case.
"""
from __future__ import annotations

import pytest

from garmin_golf_analytics import club_report, round_report


class FakeMain:
    """A main() that starts printing then hits a closed pipe."""

    def __init__(self, exception: Exception) -> None:
        self.exception = exception
        self.called_with = None

    def __call__(self, argv=None):
        self.called_with = argv
        raise self.exception


@pytest.mark.parametrize("module", [club_report, round_report])
def test_entry_point_swallows_a_broken_pipe(module, monkeypatch, capsys):
    fake = FakeMain(BrokenPipeError(32, "Broken pipe"))
    monkeypatch.setattr(module, "main", fake)
    assert module.entry_point(["somewhere"]) == 0
    assert fake.called_with == ["somewhere"]


@pytest.mark.parametrize("module", [club_report, round_report])
def test_entry_point_lets_real_errors_through(module, monkeypatch):
    """Only the closed pipe is forgiven: a genuine bug must still be visible."""
    def boom(argv=None):
        raise ValueError("real problem")
    monkeypatch.setattr(module, "main", boom)
    with pytest.raises(ValueError):
        module.entry_point([])


@pytest.mark.parametrize("module", [club_report, round_report])
def test_entry_point_returns_mains_exit_code(module, monkeypatch):
    monkeypatch.setattr(module, "main", lambda argv=None: 2)
    assert module.entry_point([]) == 2


def test_rounds_entry_point_is_wired_to_the_console_script():
    """pyproject points gga-rounds at entry_point, not main: keep them in sync."""
    from pathlib import Path
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "garmin_golf_analytics.club_report:entry_point" in pyproject
    assert "garmin_golf_analytics.round_report:entry_point" in pyproject
