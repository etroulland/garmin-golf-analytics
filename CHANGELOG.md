# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.0.16] - 2026-10-30

### Fixed

- Every iron was named one club too long: `CLUB_TYPE_NAMES` said type 14 is a
  6 Iron where Garmin calls it a 5 Iron, so a player hitting a 5 iron off the tee
  was reported as hitting a 6 iron. The table is now copied from Garmin's own
  reference endpoint, `GET /gcs-golfcommunity/api/v2/club/types`, which also
  documents the hybrids (4 to 9) and the lob wedge that were missing.
- Two tests lock the table down: one asserts the names, the other asserts the
  ids run 1 to 23 with no gap and in bag order, so a dropped type cannot fall
  back to `club:<type>` unnoticed.

## [0.0.15] - 2026-10-30

### Added

- `ruff` and `mypy` are configured in `pyproject.toml` and run in CI. The 50 lint
  findings and 20 type errors they surfaced are fixed, including two casts on the
  untyped `garminconnect` returns that were silently assumed to be lists.
- `CONTRIBUTING.md`: the rules the data imposes on any new report, the layout and
  the release process.
- `make check` runs lint, types and tests in the order CI runs them.

### Changed

- `shot_classification.py` holds what a shot was and which shots enter a table;
  `club_report.py` keeps the rendering and the CLI. Same figures, byte for byte:
  532 lines became 380 plus 117 of rules, verified by diffing the output.

### Fixed

- The PyPI author metadata said "Etienne Troulland"; it is "Etienne Roulland".

## [0.0.14] - 2026-10-29

### Added

- `gga-tee`: which club keeps your tee shot in play. Garmin's per-hole
  `fairwayShotOutcome` is joined to the club that hit the drive, giving hits,
  misses left, misses right and an in-play rate per club. A hole without a
  recorded outcome counts as `unknown` and stays out of the percentage: not
  knowing is not a hit. Only the first TEE shot of a hole counts, so a hole
  cannot contribute its outcome twice.
- `gga-courses`: the same rounds split by course, per hole and per round, with
  best/worst round, blow-up rate and putts per hole. Courses played fewer than
  `--min-rounds` times are marked; a bundle with no course name stays in the
  report as "Unknown course" instead of disappearing from it.
- Both commands take `--format json|csv` and are wired into the `gga` dispatcher.
- `gga-spread`: dispersion per club and shot kind. The p25..p75 band, standard
  deviation, `cv%` (standard deviation over the median) and the share of shots
  under 80 % of the median. Two clubs with the same median stop looking
  identical, and the band is what tells a club you can count on from one you are
  guessing with. Mishits stay out of the spread, like everywhere else.

### Fixed

- `gga-clubs` had its hole floor hard-coded at 9 while the other two reports
  read `DEFAULT_MIN_HOLES`. All three now share the constant, so `--min-holes`
  means the same thing everywhere and a change to the default lands once.

### Added

- Tests for `--min-holes` on every report: the default, a lowered floor that
  brings short rounds back, a raised one that drops a 9-hole round, the
  propagation to `gga-clubs` and both `gga-compare` modes, and a non-numeric
  value being rejected with exit 2.

## [0.0.13] - 2026-10-29

### Added

- `gga-compare --by club`: the same two windows, compared on distances. One row
  per club and shot kind with each window's median and the gap between them. A
  club hit in only one window stays a row (a new club in the bag is the change
  worth seeing), and a delta under `--min-shots` usable shots per side is
  withheld rather than computed from two swings.
- `--format json` and `--format csv` on `gga-rounds`, `gga-clubs` and
  `gga-compare`: flat, self-describing records with units in the key name and the
  period on every row. Unmeasured values stay `null`; a withheld delta is `null`
  with `low_confidence: true`. stdout carries the records alone, so they pipe
  into `jq` without scraping padded columns.

### Changed

- The club mishit floor lives in one function (`split_mishits`), read by both the
  printed table and the records, so the two can no longer disagree.

## [0.0.12] - 2026-10-29

### Added

- `gga-compare` (also `gga compare`): two date windows side by side, the signed
  delta from the first to the second. Periods are explicit (`2025` or
  `2026-01-01:2026-06-30`), never guessed months. Strokes per hole, over par per
  hole, net per hole, blow-up rate, penalties per round and 3-putt rate, so
  windows with different hole counts stay comparable. A delta under 5 rounds per
  side is printed with a low-confidence warning; one empty window exits 1.

## [0.0.11] - 2026-10-29

### Changed

- Python floor raised to 3.12, matching the requirement actually imposed by
  `garminconnect>=0.3.20` (every 0.3.x release declares `Requires-Python >=3.12`).
  0.0.10 broke `pip install` on Python 3.10 and 3.11 while claiming to support
  them. The CI matrix now runs 3.12, 3.13 and 3.14 instead of 3.10-3.13.

## [0.0.10] - 2026-10-29

### Fixed

- `garminconnect` floor raised to 0.3.20. Dropping the `<0.3` cap in 0.0.9 was
  half the fix: pip then installed 0.2.40, which cannot read a token store
  written by 0.3 and dies on `oauth1_token.json`. 0.3.20 logs in and fetches.
  `gga-fetch` is now verified end to end against the real Garmin account.

## [0.0.9] - 2026-10-29

### Fixed

- The `garminconnect<0.3` pin was wrong: 0.3.x logs in and fetches fine, and the
  pin forced pip to install an old release that could not read the token store
  written by 0.3 (`FileNotFoundError: oauth1_token.json`).

## [0.0.8] - 2026-10-29

### Added

- `gga-clubs --matrix --matrix-axis kind`: the same club x column table, but the
  columns are what the shot was (tee, approach, chip...). Splits a club that is
  used for two different jobs instead of averaging them: a 6-iron tees off and
  approaches at distances far enough apart to make a single median useless.

### Fixed

- `--matrix` exits 1 when the requested columns hold no shot, instead of
  printing nothing and reporting success.

## [0.0.7] - 2026-10-29

### Added

- `gga-clubs --matrix`: one table with clubs in rows and lies in columns, the
  median distance in each cell with its sample size, `-` where nothing was
  tracked and a `*` under the sample threshold. `LIES` is comma-separated and
  defaults to `TeeBox,Fairway`; an unknown lie name is refused with exit 2
  rather than silently printing an empty column.

## [0.0.6] - 2026-10-29

### Fixed

- `gga-clubs rounds/ | head` no longer ends in a `BrokenPipeError` traceback.
  Piping into `head`, `less` or `grep -m1` is how this output is normally read,
  so the console scripts now exit 0 when their reader closes the pipe. A real
  exception still propagates.

## [0.0.5] - 2026-10-29

### Fixed

- `UNKNOWN` shots are no longer dropped. Garmin leaves a large share of tracked
  shots without a `shotType`; the report skipped them without saying so, which
  shrank every sample. They are now classified from the lie, the hole's par and
  the distance, and whatever is still guessed is printed as `Unclassified` with
  its share of the sample.
- The `TeeBox` lie no longer implies a tee shot. Garmin tags the FIRST shot of
  a hole `TeeBox` whatever club was hit, so a 7-iron opened on a par 4 was
  counted as a drive. A first shot on a par 4 or 5 with a club short of a wood
  is now `Layup (tee)`; a par 3 tee shot stays a tee shot.
- A putter shot from the fringe counts as a putt in both views instead of
  drifting into the chip rows.

### Added

- `gga-clubs --by-shot-type`: one row per (club, shot kind) instead of per lie,
  so a chip and a tee shot of the same club stop sharing a median.

## [0.0.4] - 2026-10-29

### Added

- `release.yml`: publishing to PyPI on a `v*` tag through Trusted Publishing
  (OIDC, `id-token: write`). Builds and tests run before the upload; no API
  token is stored anywhere.

### Fixed

- The package metadata pointed `Changelog` at a `master` branch that does not
  exist on the remote.

## [0.0.3] - 2026-10-29

### Added

- Installable package: `pyproject.toml` (PEP 621, setuptools, `src/` layout),
  console scripts `gga`, `gga-fetch`, `gga-clubs`, `gga-rounds`, and a `gga`
  dispatcher (`gga fetch|clubs|rounds`). `pipx install garmin-golf-analytics`
  is now the supported install path; cloning is for development.
- CI (`.github/workflows/tests.yml`): pytest and the 90 % coverage gate on
  Python 3.10 to 3.13, plus a check that every console script resolves.
- `tests/test_cli.py`: the dispatcher's help, unknown-command and argv
  forwarding paths.

### Removed

- `requirements-dev.txt`. It duplicated the `dev` extra with an unpinned
  `garminconnect` and no version floor; `pip install -e '.[dev]'` is the
  documented path.

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
- `shotType` (APPROACH / TEE / CHIP / LAYUP / UNKNOWN) is not used yet, so a chip
  and an approach of the same length still share a row. `UNKNOWN` is 23% of the
  tracked shots and is silently dropped from the distance table.

Resolved in [0.0.3]: the package is installable (`pyproject.toml`, entry points,
pinned `garminconnect`) and `--min-meters` defaults to no floor.
