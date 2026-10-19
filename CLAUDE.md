# Meliora

Keenan's personal assistant: a native-feeling Mac app that tells him what to do next, plans his day around school, his flexible virtual job, and training, and keeps him accountable without nagging. It is built and used by one person: Keenan (Mines ME sophomore, Python-comfortable, runs/lifts/climbs 14ers).

The design rationale lives in `docs/SYNTHESIS.md`, which records what was kept and cut and why. The target look is `docs/mockup.html`, a static mockup you can open in a browser. Read both before making product decisions. Planning happens in a separate Claude chat that may update this file; when a request conflicts with this file, ask.

## Hard constraints
- **Mac-first app** that opens from the Dock. Phone access is a nice-to-have.
- **Offline matters more than phone access.** Everything core must work with no network: a local model, cached data, no web fonts.
- **Free.** Claude tokens are the only cost. No paid APIs, no SMS services. **No email notifications.**
- **Private.** Data stays on the Mac. Only prompts sent to Claude leave it, and every Claude call is logged with its token count.

## Stack
- **Python 3.12+**, managed with `uv`. 3.12 is required by `garminconnect`.
- **UI:** `pywebview` gives a native WKWebView window with an HTML/CSS/JS front end in `ui/`. Python is exposed to JS via `js_api`; no web server is needed. Port `docs/mockup.html` as the starting point. For the Dock, use **py2app alias mode** (`py2app -A`). It builds `Meliora.app` with a proper name and icon that runs the live source in this repo, so code edits apply on relaunch and only Info.plist or icon changes need a rebuild. A shell-script wrapper is an acceptable first step, but it shows as "Python" in the Dock. A menu-bar item comes later; Tauri or SwiftUI is only reconsidered if pywebview hits a wall.
- **Engine:** a Python package `meliora/`. Collectors write to SQLite, deterministic rules produce decisions, and a model router phrases the output. It is run by `launchd` (morning run plus periodic refresh).
- **Models:** Ollama with Qwen3 locally (default and offline), `claude -p` when online for the Sunday plan, chat, and hard phrasing. The router logs every Claude call.
- **Secrets** (Canvas token, Garmin tokens, app passwords) go in macOS Keychain via `keyring`. They never go in git or the vault.
- **Data:** `data/` holds the SQLite database and logs. It is gitignored and must never be inside iCloud.

## Who does what
- **Python with no model:** all scheduling and placement (a scoring heuristic first, OR-Tools CP-SAT if it gets hairy), The Call, crunch detection, job windows, notification budget. This must work offline.
- **Local model (Qwen3 via Ollama), structured JSON only:** turning natural-language requests ("fit 2 h of job work Thursday") into a structured intent the scheduler executes, classifying emails and reminders, extracting dates (always shown for confirmation), phrasing The Sentence and Today.md, quick chat about today's data. Use the largest model that runs comfortably on the M4 Max with 64 GB (e.g. Qwen3-30B-A3B or 32B at 4-bit), with a smaller fast model for instant UI phrasing.
- **Claude (`claude -p`, online only):** workout programming and training advice, the Sunday weekly plan, judgment-heavy tradeoffs, and writing that matters (applications, important emails). Send structured summaries, not raw dumps, and log tokens. Results are written to the vault (e.g. `Assistant/Training.md`) so they reach the phone and any Claude chat can read them. When offline, fall back to the local model and mark the output as provisional.
- **Billing:** `claude -p` runs on Keenan's Claude subscription, not paid API credits. Never call the Anthropic API directly. Make sure `ANTHROPIC_API_KEY` is **unset** in the shell and the launchd environment; if it's set, Claude Code switches to pay-per-use API billing. Usage counts against the same limits as his Claude chats, so keep calls few and prompts compact.

## Core design rules (non-negotiable)
1. **Rules decide, the model phrases.** Scheduling, readiness, and alerts are plain Python. The LLM only turns structured results into words. Offline Qwen3 must produce a usable day.
2. **Pencil before ink.** The app never writes to Keenan's calendar without a Confirm. Proposed blocks are drawn dashed. Confirmed blocks go to a dedicated calendar named "Meliora", so a bad plan can be deleted in one step.
3. **Receipts.** Any praise, criticism, or insight shown must cite a real number or date from the data. If it can't, it isn't shown.
4. **Quiet by default.** Mac notifications are capped at 3 a day, global across all features. If he ignores 3 nudges in a row, the push level drops one step.
5. **Degrade honestly.** Every source can fail (Garmin is unofficial and fragile). The UI shows a per-source "last synced" footer and keeps working without that source.
6. **No streaks, no calorie corrections, no real-time app-watching.** These were cut on purpose; see SYNTHESIS.md.
7. **Planned rest is protected.** Netflix and Minecraft are "chosen rest" and never judged. Only unplanned YouTube "drift" can be roasted, and only if he opts in.

## Obsidian vault contract
- Path: `/Users/keenanmanchester/Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault`. It contains spaces and tildes, so always use `pathlib` and keep it in one config value.
- The vault syncs to his phone via iCloud. That is the free mobile path.
- **Read** anything. Known useful inputs: `TODO.md`, `Workouts.md`, `Workout Plan.md`, and `Mines/`. Inspect their real format before writing parsers.
- **Write only inside `Vault/Assistant/`**, and only files the app owns (`Today.md`, `Week.md`, reviews). Never edit Keenan's own notes.
- **Atomic writes:** write a temp file in the same folder, then `os.replace`. This keeps Obsidian and iCloud from seeing half-written files.
- **Phone input** goes in `Assistant/Inbox.md`, which Keenan writes and the app only reads. Track processed lines in SQLite. Never rewrite that file; doing so causes "Inbox 2.md" iCloud conflicts.
- Keenan should set the vault to "Keep Downloaded" in Finder so files are never cloud-only placeholders.

## macOS gotchas
- `launchd` jobs can't show permission prompts. The **real** Python binary (resolve the venv symlink to the uv-managed interpreter) needs **Full Disk Access**. That covers the iCloud vault and Screen Time (`knowledgeC.db`, Biome). Calendar and Reminders (EventKit via pyobjc) need their own grant, so trigger it once from Terminal.
- `launchd` doesn't run while the lid is closed. The morning job must catch up on wake. An optional `pmset` wake at 6:25 works when the Mac is plugged in.
- Run heavy local-model passes only on AC power.
- The Mac can't push anything while asleep. Phone alerts are pre-scheduled as Apple Reminders and calendar alerts, which iCloud delivers.

## Build order
### Phase 0 (now)
1. **Health check first:** a tiny script, run once by hand and once under `launchd`. It reads a vault note, writes `Assistant/_healthcheck.md`, and reads one Calendar event. This proves permissions before anything depends on them.
2. Project skeleton: `uv` project, `meliora/` package, `config.toml`, SQLite schema, logging.
3. Collectors: Calendar and Reminders (EventKit), Canvas (API token, ICS fallback), weather (Open-Meteo for Golden, CO, plus NWS alerts).
4. A rules engine that picks **The Sentence** (the single next action and why) and lays out today's timeline.
5. A pywebview window showing The Sentence, the Next card, and the day timeline, ported from `docs/mockup.html` and fed real data. It follows macOS light/dark mode.
6. Write `Assistant/Today.md`, send one morning Mac notification, and set up the 6:30 `launchd` job.
7. A chat drawer with a Qwen3/Claude toggle that can read today's data.

Add one new data source per week after Phase 0.

### Phase 1
Garmin (`garminconnect`) and **The Call** (GO/EASY/REST, with trust badges and a feel tap). Pencil/ink proposals into the "Meliora" calendar. Start-by dates and the 3-week horizon strip. Job window finder and weekly hours target. Evening close and the Sunday plan. Push level, Back-off, and Rough week mode. The source health footer.

### Phase 2 and later
See SYNTHESIS.md. Highlights: Screen Time with rest windows, migrating Keenan's existing Python weight tracker in alongside the training log, Summit Windows for 14ers, commitments, and the Apple Mail "needs reply" check.

## Defaults until Keenan decides otherwise
The pending decisions are listed in SYNTHESIS.md. Until he decides:
- Notification cap: 3 a day.
- Push level: Normal.
- The screen-time roast is off until he opts in.
- Theme follows macOS light/dark.
- In crunch weeks, deadlines within 24 h win over training. Training volume drops but frequency doesn't.

## Working agreements
- Ask before anything that writes to his calendar, Reminders, or vault (beyond `Assistant/`), or deletes data.
- Keep it simple. Explain macOS-specific steps he has to do by hand (permission grants, Keychain entries) in plain steps.
- Commit in small working increments. The repo is meant to be pushed to a private GitHub repo.
