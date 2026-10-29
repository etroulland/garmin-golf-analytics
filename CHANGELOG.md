# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Installable package: `pyproject.toml` (PEP 621, setuptools, `src/` layout),
  console scripts `gga`, `gga-fetch`, `gga-clubs`, `gga-rounds`, and a `gga`
  dispatcher (`gga fetch|clubs|rounds`). `pipx install garmin-golf-analytics`
  is now the supported install path; cloning is for development.
- CI (`.github/workflows/tests.yml`): pytest and the 90 % coverage gate on
  Python 3.10 to 3.13, plus a check that every console script resolves.
- `tests/test_cli.py`: the dispatcher's help, unknown-command and argv
  forwarding paths.

### Changed

- The six modules moved from the repo root to `src/garmin_golf_analytics/`.
  Intra-package imports are now relative; nothing imports `garminconnect`
  unless `gga fetch` runs, so `gga clubs` and `gga rounds` work without it.
- `garminconnect` is a declared dependency pinned to `>=0.2.19,<0.3` instead of
  an unpinned manual install.
- pytest and coverage settings moved from `pytest.ini` into `pyproject.toml`.
  `run_tests.sh` relies on that config instead of repeating the file list.

- Putter approaches get their own row. A putt played from the fairway, the rough
  or a bunker and stopping on the green is reported as `Putter (approach)`; a
  putt played from the green is still dropped as short game. Garmin tags both
  the same way, so the lie decides.

### Changed

- Mishits are relative to the club: a shot under 60 m counts as a mishit, or
  under half the club's own median when that is lower. A flat 60 m floor hid
  every wedged shot behind a `n=0` row.

## [0.0.2] - 2026-10-28

Reports stop claiming more than the data says. See the entries below, which were
written for this release.

### Added

- `rounds_common.py`: the round selection rules (Garmin `excludeFromStats`,
  partial rounds, practice rounds) in one place, shared by both reports. Each
  dropped round now has exactly one reason, and the reports print the counts
  per reason instead of a single opaque "dropped" number.
- `--keep-excluded` on `club_report.py` and `round_report.py` to include rounds
  Garmin flagged `excludeFromStats`.
- `--min-holes` on `club_report.py`, so both reports can be tuned to the same
  sample.
- `round_report.py`: `putts_are_measured()` and `putt_status()`. Every round is
  labelled `sensor`, `manual entry, sensor off` or `no putt data (sensor off,
  no entry)`.
- `scoring.py`: per-hole par and relative score. `garmin_golf_fetch.py` now keeps
  `courseSnapshots` in a `course` block of every bundle (course name, city,
  country, `holePars`, `roundPar`). `round_report.py` prints `par`, `to_par` and
  `net` per round plus medians, instead of refusing to talk about par.
- `hole_sync.py`: per-hole reconciliation between the scorecard and the tracked
  shots. The reports now print how many strokes the watch never recorded
  (`untracked=N strokes on M holes`, plus a global share), because a round's
  score and its shot list routinely disagree and nothing said so.
- Test suite (`tests/`, 117 tests) with synthetic round bundles, plus
  `run_tests.sh` and `requirements-dev.txt`. Coverage gate at 90 %; the suite
  currently sits at 98 %.

- `--min-meters` now defaults to no floor. One threshold for every club deleted
  the wedges from their own table (a Sand Wedge has 3 tracked shots, 9 mishits);
  mishits are counted separately, so the floor had no job left.
- Shots whose club cannot be named are excluded from the distance report
  instead of appearing as `clubId:<n>`.
- `garmin_golf_fetch.py` no longer stores Garmin's `scorecard.score`, a net score
  built on `handicappedStrokes` that reads wrong on partial rounds.

### Changed

- `club_report.py`: distances are documented and printed as **total** distance
  (GPS, start point to end point, roll included). Garmin stores no carry, and
  the module used to call its numbers "carry". The `--min-meters` help text and
  the report header now say total.
- `club_report.py`: the per-club table drops p25/p75/p90 for `med`, `good%`
  (share of shots ending on the fairway or the green), `max` and `mishits`
  (shots under 60 m, kept out of the median). Percentiles described a club
  nobody plays: a tight p25-p75 can still leave two thirds of the balls in the
  rough, and a median diluted by tops and chips is not a club distance.
- `club_report.py` now uses the same round selection as `round_report.py`. It
  previously ignored Garmin's `excludeFromStats` flag, so the distance table and
  the score table were built on two different samples.
- `garmin_golf_fetch.py`, `club_report.py`, `round_report.py`: `main()` accepts
  an explicit argv, which makes the CLIs testable.
- Club names no longer need a manual data export. `get_golf_club_stats()` lists
  every club with its `clubTypeId`, and a verified type table gives the label.
  `--zipref` stays as an override for the loft, which the API does not expose.

### Fixed

- `club_report.py` no longer lists the Putter as a club: Garmin records a few
  PUTT shots and they polluted the distance table.
- Putt data is no longer presented as measured when it is not. Garmin cannot
  detect putts without its club sensors; with the sensor off the count is
  either manual entry or a constant fill of 2 on every hole. A constant count
  is dropped as fill (this already happened by accident), and the report now
  says so explicitly instead of silently averaging a number that was typed in.
- Dropped rounds were lumped into one `partial/practice` counter, which hid
  rounds Garmin itself excluded from statistics.
- Per-hole par was reported as unavailable. It is in `courseSnapshots`, a
  sibling of `scorecardDetails` that the fetch script threw away. Read that
  block only and `holePars` is invisible, which is why every bundle lacked par.
- `scorecard.score` is not `strokes - par - playerHandicap`. It is
  `strokes - par - handicappedStrokes`, where `handicappedStrokes` counts the
  strokes received on the holes actually played. Subtracting `playerHandicap`
  from a nine-hole round is off by tens of strokes.

### Documentation

- README: replaced the "real carry distances" claim with measured total
  distances, documented the putt limitation and the `sensorOnPutter` flag, and
  added the `startLoc.lie == "TeeBox"` caveat: it marks the first shot played on
  a hole, not a shot hit from the tee.

### Known limitations

- `startLoc.lie == "TeeBox"` is the lie of the first shot played on a hole, not
  the tee box. A par 4 played 5-iron then wedge tags the 5-iron `TeeBox` and the
  wedge `Fairway`. Filtering on `TeeBox` is not "tee shots only".
- `--min-meters` (default 40) applies one floor to every club, which starves the
  wedges of full-swing samples. Still unchanged by design.
- No `pyproject.toml`, no entry points, `garminconnect` not pinned.
- `shotType` (APPROACH / TEE / CHIP / LAYUP / UNKNOWN) is not used yet, so a chip
  and an approach of the same length still share a row. `UNKNOWN` is 23% of the
  tracked shots and is silently dropped from the distance table.
