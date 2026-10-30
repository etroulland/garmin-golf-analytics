# garmin-golf-analytics

[![PyPI](https://img.shields.io/pypi/v/garmin-golf-analytics.svg)](https://pypi.org/project/garmin-golf-analytics/)
[![Python versions](https://img.shields.io/pypi/pyversions/garmin-golf-analytics.svg)](https://pypi.org/project/garmin-golf-analytics/)
[![tests](https://github.com/etroulland/garmin-golf-analytics/actions/workflows/tests.yml/badge.svg)](https://github.com/etroulland/garmin-golf-analytics/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Pull your Garmin Connect golf rounds and turn them into numbers you can act on: measured shot
distances per club, split by lie, plus a round debrief that isn't fooled by Garmin's own
defaults.

Garmin already stores every shot its sensors caught. This repo reads that data through the
`garminconnect` API instead of asking you to download a `DI_CONNECT` zip by hand, then applies
the parsing rules that make the numbers trustworthy.

## Why this exists

The Garmin golf data looks clean and isn't. Things that silently corrupt a naive analysis:

- **No putt detection without the sensors.** The watch only counts putts with the Garmin club
  sensors on the putter. Without them nothing is measured: any `putts` value is whatever was typed
  in by hand, and Garmin's own default fill is `putts: 2` on every hole. Averaging that gives a
  perfect two-putt game you don't have, and `sensorOnPutter` is your only way to know which is
  which.
- **No per-hole par on the hole itself.** `holes[].par` is always `null`, but the pars of the
  course are in `courseSnapshots[].holePars`, a digit string ordered 1..18, in the same response.
  Garmin's own `score` field is a NET score and uses `handicappedStrokes`, not the course handicap.
- **Uneven sampling.** One club can read 185 m off the tee and 108 m from the fairway, because
  most of its fairway shots are punch-outs. Pooling the two produces a number that describes no
  shot you ever hit.
- **Short-game pollution.** A gap wedge chips from 20 m all day long. Include those in its average
  and it looks 40 m shorter than it plays with a full swing.
- **Club identity gaps.** `clubId: 0` marks swings the watch could not attribute to a club. They
  are not a club and must never appear as one.
- **Partial rounds.** Abandoned rounds and range sessions land in the same feed as real ones.

## Install

```bash
pipx install garmin-golf-analytics
```

Or from a clone, with the test suite:

```bash
git clone https://github.com/etroulland/garmin-golf-analytics
cd garmin-golf-analytics
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

Log in once. `garminconnect` writes a token store, so no credentials ever live in this repo:

```bash
python -c "from garminconnect import Garmin; Garmin().login()"
# answer the prompts once; the session is cached in ~/.garminconnect
```

## Fetch rounds

```bash
export GARMINTOKENS=~/.garminconnect
gga-fetch                 # latest round only
gga-fetch --days 30       # every round played in the window
gga-fetch --scid 383676990
```

The same commands are available as subcommands of a single `gga` dispatcher:
`gga fetch`, `gga clubs`, `gga rounds`.

Each round becomes `rounds/round_<YYYY-MM-DD>_<scid>.json`:

```json
{
  "scorecard": { "startTime": "...", "strokes": 46, "handicappedStrokes": 9, "holes": [...] },
  "course": { "name": "Golf Club St. Meard", "roundPar": 32, "pars": { "1": 3, "2": 3, "...": 0 } },
  "shots": { "1": [{"clubId": 788036363, "meters": 181.9, "startLoc": {"lie": "TeeBox"}}] },
  "playedHoles": 9
}
```

`course` comes from `courseSnapshots`, a sibling of `scorecardDetails` in the same API response.
It carries the per-hole par that `holes[].par` never does. `pars` is keyed by hole **number**: a
`BACK_9` round lists holes 10..18, so join on the number, never on the position in the array.

Club names need `Golf-CLUB.json` and `Golf-CLUB_TYPES.json`, which only ship inside a Garmin
data export. Point `--zipref` (or `$GARMIN_ZIPREF`) at a `DI-GOLF` directory to get them joined in.
Club names come from the API (`get_golf_club_stats`), which returns every club with its
`clubTypeId` but never the label. `--zipref` is still accepted and overrides it, because only a
data export carries the loft per club. Shots whose club cannot be named are excluded from the
distance report rather than shown as `clubId:<n>`, which no one can act on.

## Club distances

```bash
gga-clubs rounds/
gga-clubs rounds/ --lie TeeBox        # shots played from the tee box, whatever the club
gga-clubs rounds/ --min-meters 40     # raise the floor to drop chips
gga-clubs rounds/ --by-shot-type      # one row per (club, shot kind)
gga-clubs rounds/ --matrix            # clubs x lies table, TeeBox and Fairway
gga-clubs rounds/ --matrix TeeBox,Fairway,Rough,Bunker
gga-clubs rounds/ --matrix --matrix-axis kind   # columns are tee/approach/chip
```

Median, p75, p90 and max per club **per lie**, because that is how the numbers are actually usable
on the course. Clubs under 5 tracked shots are flagged `(low n)`.

Every distance is a **total** distance: Garmin stores one `meters` value per shot, from the start
point to the end point, roll included. Carry is not in the data and is not reported.

`startLoc.lie == "TeeBox"` means "first shot played on that hole", not "hit from the tee": a par 4
played 5-iron then wedge tags the 5-iron TeeBox and the wedge Fairway. `--by-shot-type` handles
that: a first shot on a par 4 or 5 with a club short of a wood is reported as `Layup (tee)`, a
par 3 tee shot stays `Tee`.

Garmin leaves a good share of tracked shots with no `shotType` at all. Those are kept and
classified from the lie, the par and the distance; whatever is still unresolvable closes the table
as `Unclassified`, with its share of the sample printed above it. It is never silently dropped.

Garmin records only a fraction of the swings you take, so n is small for a long time. Treat
anything under 5 shots as noise and never let one low-n club outrank a measured one.

## Round debrief

```bash
gga-rounds rounds/
```

Strokes per hole distribution, blow-up rate, penalties per round, and three-putt rate. Rounds with
fewer than 9 played holes, or under 35 strokes on 9 / 60 on 18, are dropped as practice or
abandoned before anything is averaged.

## Compare two periods

```bash
gga-compare rounds/ --period 2025 --period 2026            # whole calendar years
gga-compare rounds/ --period 2026-01-01:2026-06-30 --period 2026-07-01:2026-12-31
```

Two windows side by side, with the signed delta from the first to the second. Every figure is
per hole or a rate: a 9-hole over-par and an 18-hole one are not the same number, so they are
never compared raw. Windows are explicit dates, never guessed months, and a delta computed on
fewer than 5 rounds per side is printed with a low-confidence warning instead of being presented
as progress. Putts are counted only on rounds Garmin actually measured.

`--by club` compares distances instead of scoring: one row per club and shot kind, the median of
each window and the gap between them.

```bash
gga-compare rounds/ --period 2025 --period 2026 --by club
```

A club hit in only one window is still a row, with the other side left blank: a club that entered
the bag is exactly the change worth seeing. A distance delta needs `--min-shots` usable shots on
each side (default 5) and is withheld below that, never extrapolated from two swings.

## Tee accuracy

Distance says how far a club goes. It does not say whether the ball stays in play, and that is the
question a tee shot answers. Garmin records the drive's outcome per hole, so the two are joined
without modelling anything.

```bash
gga-tee rounds/
```

One row per club used off the tee: hits, misses left, misses right, and the share that stayed in
play. A hole Garmin left without an outcome is counted as `unknown` and excluded from the
percentage, never assumed a hit or a miss. A club with few recorded outcomes is flagged rather than
ranked.

## How repeatable each club is

The median is a promise the shots do not always keep. Two players with a 170 m driver do not play
the same game if one hits 168 to 172 and the other alternates 140 and 200.

```bash
gga-spread rounds/
```

Per club and shot kind: the p25..p75 band (half the shots land inside it), the standard deviation,
`cv%` (standard deviation over the median, so a wedge and a driver can be compared) and `short%`,
the shots under 80 % of the median. A shrinking band is a club you can count on; a growing one is a
club you are guessing with, whatever its median says. Mishits stay out of the spread, as everywhere
else.

## One row per course

A single figure averages courses that have nothing in common. The same rounds, split by course:

```bash
gga-courses rounds/
```

Per hole and per round, so a course played once sits next to one played twenty times; the ones
played fewer than `--min-rounds` times are marked. Putts per hole only count the rounds Garmin
actually measured.

## Machine-readable output

`gga-rounds`, `gga-clubs`, `gga-compare`, `gga-tee`, `gga-courses` and `gga-spread` take
`--format json` or `--format csv`. Both write
records and nothing else on stdout, so they pipe into `jq` or a spreadsheet without scraping padded
columns.

```bash
gga-rounds rounds/ --format csv > rounds.csv
gga-compare rounds/ --period 2025 --period 2026 --by club --format json | jq '.[] | select(.delta_m)'
```

Every record is flat and self-describing: units live in the key (`median_m`, `blowup_holes_percent`,
`penalties_per_round`), periods are named on every row so two comparisons can be concatenated, and
an unmeasured value stays `null` instead of becoming a zero. A withheld delta is `null` with
`low_confidence: true`, which is a different statement from "no change".

## Layout

```
src/garmin_golf_analytics/
  garmin_golf_fetch.py  fetch rounds from the Garmin API
  shot_classification.py what a shot was, which shots enter a table
  club_report.py        distance tables per club, split by lie
  round_report.py       score, penalties, blow-up holes, putting
  compare_report.py     two date windows, per-hole or per-club figures and their delta
  output.py             --format json/csv records shared by every report
  tee_report.py         which club keeps the tee shot in play
  course_report.py      the same rounds, one row per course
  spread_report.py      dispersion per club: band, standard deviation, short shots
  rounds_common.py      which rounds count, shared by every report
  scoring.py            per-hole par and relative score
  hole_sync.py          tracked shots vs scorecard reconciliation
  cli.py                the `gga` dispatcher
tests/                  one file per module, 265 tests, 93% coverage
```

## Development

```bash
pip install -e '.[dev]'
make check        # ruff + mypy + pytest with the coverage gate
```

CI runs all three on Python 3.12 to 3.14 and checks that every console script
resolves (`.github/workflows/tests.yml`). See [CONTRIBUTING.md](CONTRIBUTING.md)
for the rules the data imposes on any new report.

## License

MIT

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
