# Contributing

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

`pip install -e '.[dev]'` is the only supported development path. There is no
`requirements.txt` on purpose: `pyproject.toml` is the single source of truth for
dependencies and versions.

## Before opening a pull request

```bash
make check
```

All three run in CI on Python 3.12, 3.13 and 3.14, plus a check that every console
script resolves. The coverage gate is 90 % and the build fails below it.

## The rules that are not negotiable

These come from the data, not from taste. Each one exists because ignoring it
produced a number that was wrong.

**A missing measurement is not a zero.** When Garmin has no value, the record
carries `null` and the figure is withheld or explicitly qualified. It is never
folded in as 0, and a percentage never divides by a total that includes the
unknowns.

**Distances are total, roll included.** Garmin stores one `meters` value per shot
from the start point to the end point. There is no carry in the data. Never label
one of these figures "carry".

**Mishits are relative.** A shot only counts as a mishit below
`min(60 m, half the club's own median)`, through `split_mishits()`. A wedge never
plays 60 m and a driver never plays 12: a fixed floor silently deletes the wedges
and inflates the drivers.

**One sample, one set of rules.** The round selection lives in `rounds_common.py`
and the shot rules in `shot_classification.py`. A report that computes its own
selection or its own mishit floor will disagree with the others, and the user has
no way to tell which one is right.

**`uncertain` is written, never hidden.** When the data cannot support a figure,
the output says so: `(low n)`, a coverage count next to a rate, a withheld delta.
Silence is what makes a report lie.

## Layout

```
src/garmin_golf_analytics/
  fetch / garmin_golf_fetch.py   Garmin API -> JSON bundles
  rounds_common.py               round selection, bundle loading
  shot_classification.py         what a shot was, which shots count
  scoring.py                     net score, par, relative score
  output.py                      json and csv rendering
  round_report.py                one row per round
  club_report.py                 distances per club and lie
  compare_report.py              two windows side by side
  tee_report.py                  tee shot accuracy per club
  course_report.py               one row per course
  spread_report.py               dispersion per club
  cli.py                         the `gga` dispatcher
```

Rules and computation live in the modules without `_report` in their name.
A `*_report.py` module groups, renders and parses arguments; it does not decide
what a shot is.

## Tests

One test file per module, named after it. A test asserts a behaviour the report
promises, not the internal shape of a function: changing how a figure is computed
should not break a test that checks the figure is right.

## Adding a report

1. A new `*_report.py` with `main()`, `entry_point()` and a module docstring
   stating what question the report answers.
2. A `[project.scripts]` entry in `pyproject.toml`.
3. A case in `cli.py`.
4. A `tests/test_<name>.py`.
5. A section in `README.md` and an entry under `Unreleased` in `CHANGELOG.md`.

## Releasing

Version lives in `src/garmin_golf_analytics/__init__.py`. A tag `vX.Y.Z` on
`main` triggers CI, which builds, publishes to PyPI through Trusted Publishing
and opens the GitHub release. Never retag: PyPI refuses to overwrite a version,
so a bad release becomes the next patch.
