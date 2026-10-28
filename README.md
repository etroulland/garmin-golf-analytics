# garmin-golf-analytics

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
python -m venv .venv
source .venv/bin/activate
pip install garminconnect
```

Log in once. `garminconnect` writes a token store, so no credentials ever live in this repo:

```bash
python -c "from garminconnect import Garmin; Garmin().login()"
# answer the prompts once; the session is cached in ~/.garminconnect
```

## Fetch rounds

```bash
export GARMINTOKENS=~/.garminconnect
python garmin_golf_fetch.py                 # latest round only
python garmin_golf_fetch.py --days 30       # every round played in the window
python garmin_golf_fetch.py --scid 383676990
```

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
python club_report.py rounds/
python club_report.py rounds/ --lie TeeBox      # first shot of a hole (see caveat below)
python club_report.py rounds/ --min-meters 40   # raise the floor to drop chips
```

Median, p75, p90 and max per club **per lie**, because that is how the numbers are actually usable
on the course. Clubs under 5 tracked shots are flagged `(low n)`.

Every distance is a **total** distance: Garmin stores one `meters` value per shot, from the start
point to the end point, roll included. Carry is not in the data and is not reported.
`startLoc.lie == "TeeBox"` means "first shot played on that hole", not "hit from the tee": a par 4
played 5-iron then wedge tags the 5-iron TeeBox and the wedge Fairway.

Garmin records only a fraction of the swings you take, so n is small for a long time. Treat
anything under 5 shots as noise and never let one low-n club outrank a measured one.

## Round debrief

```bash
python round_report.py rounds/
```

Strokes per hole distribution, blow-up rate, penalties per round, and three-putt rate. Rounds with
fewer than 9 played holes, or under 35 strokes on 9 / 60 on 18, are dropped as practice or
abandoned before anything is averaged.

## Layout

```
garmin_golf_fetch.py   fetch rounds from the Garmin API
club_report.py         distance tables per club, split by lie
round_report.py        score, penalties, blow-up holes, putting
```

## License

MIT

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
