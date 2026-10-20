# Meliora

A personal Mac assistant that tells me what to do next. It opens on one sentence,
the single next action and why, with the day's timeline underneath. It plans around
classes, a flexible job, and training, and stays quiet unless something matters.

Built for one person (me), so it's opinionated. The design notes in `docs/` explain
what was kept, what was cut, and why. `docs/mockup.html` is the target look.

## Design rules

- **Rules decide, the model phrases.** Scheduling and alerts are plain Python. A local
  model (or Claude, when online) only turns the results into words.
- **Pencil before ink.** Suggested blocks are drawn dashed until confirmed.
- **Receipts.** Every insight cites a real number or date, or it isn't shown.
- **Offline first, private by default.** Data stays on the Mac.

## Run it

Needs macOS and [uv](https://docs.astral.sh/uv/).

```sh
uv run meliora                 # open the window (uses the fake sample data)
MELIORA_DEBUG=1 uv run meliora # with right-click → Inspect Element
uv run meliora-weather         # fetch weather now and print a snow summary
./scripts/make_app.sh          # build ~/Applications/Meliora.app for the Dock
```

The `.app` is a thin launcher that runs the code in this repo, so edits to
`src/meliora/` show up the next time you open it. Logs go to `data/app.log`.

## Your data vs. the sample

Everything personal lives in `data/`, which is gitignored. `data-sample/` holds a
fake copy of each file so a fresh clone runs with no setup. For each file, the app
reads `data/<file>` if it exists, otherwise `data-sample/<file>`.

To make it yours:

```sh
mkdir -p data && cp data-sample/* data/
```

Then edit `data/config.toml` (home location, vault path, mountains and resorts) and
`data/demo_day.json` (the demo schedule, until the Calendar collector lands).

## Layout

- `src/meliora/rules.py` decides The Sentence from the day's blocks and the clock.
- `src/meliora/weather.py` pulls ECMWF + NAM (Open-Meteo) for every place in the config,
  plus NWS alerts and the home forecast. Refreshed in the background on launch when over 3 h old.
- `src/meliora/config.py` loads settings and picks `data/` or `data-sample/`.
- `src/meliora/db.py` is SQLite in `data/`.
- `src/meliora/app.py` is the pywebview window. Methods on `Api` are callable from JS as `pywebview.api.*`.
- `src/meliora/ui/` holds the HTML, CSS and JS front end. The sky follows the real sun
  position at your home location.
