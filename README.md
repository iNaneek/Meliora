# Meliora

Keenan's personal assistant. See `CLAUDE.md` for the plan and `docs/` for the design.

## Run it

```sh
uv run meliora                 # from Terminal
MELIORA_DEBUG=1 uv run meliora # with right-click → Inspect Element
./scripts/make_app.sh          # (re)build ~/Applications/Meliora.app
```

The `.app` is a thin launcher that runs the code in this repo, so edits to
`src/meliora/` show up the next time you open it. No rebuild is needed. Logs go to `data/app.log`.

## Layout

- `src/meliora/rules.py` decides The Sentence from the day's blocks and the clock (demo day for now).
- `src/meliora/db.py` is SQLite in `data/` (gitignored).
- `src/meliora/app.py` is the pywebview window. Methods on `Api` are callable from JS as `pywebview.api.*`.
- `src/meliora/ui/` holds the HTML, CSS and JS front end, ported from `docs/mockup.html`.
