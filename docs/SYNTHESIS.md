---
title: Assistant Ideation Synthesis
date: 2026-10-18
tags: [assistant-dev, planning]
status: decisions-pending
---

# Assistant Ideation Synthesis

Six designers each pitched ideas and a mockup, then critiqued each other. This note is the final call: what to build, what to cut and why, what you still need to decide, and a build order. The raw idea files, critiques and mockups are in the `ideation/` folder.

**The panel:**
- **Mara (Minimalist):** one decision a day; silence is a feature.
- **Dex (Maximalist):** a chief of staff that joins every data source.
- **Dr. Raman (Academic):** sees crunch weeks early; protects deep work.
- **Coach Rhys:** trains by readiness; hybrid training; plans around mountain weather.
- **Dr. Adeyemi (Behavior Psychologist):** makes accountability welcome; owns the assistant's voice.
- **Gwen (Secretary):** treats time as a 168-hour budget; keeps the calendar true.

---

## The one-paragraph version

Build a Mac app that opens on **one sentence telling you what to do next**, with your day underneath it. The assistant **proposes**: blocks it suggests show in pencil until you tap Confirm, and only then are they written to a separate calendar. **Rules decide and the model only writes the words**, so it works offline with Qwen3 and gets better with Claude. Every claim it makes shows its source. It gets **quieter when you ignore it** and **gentler in a bad week**. Your Obsidian vault and Apple Reminders are the free route to your phone.

---

## Where all six agreed

These came up independently from every designer, or survived every critique.

- **Propose, never auto-write.** Suggested blocks are drawn in pencil until you confirm them (Secretary's idea, adopted by all six). Confirmed blocks go to a dedicated calendar, so a bad plan can be deleted in one tap.
- **Rules choose, the model phrases.** Scheduling, readiness and alerts come from deterministic Python. The LLM only turns them into words. This is what makes offline Qwen3 good enough.
- **Planned rest is protected; unplanned scrolling is what gets roasted.** Netflix and Minecraft sit in a "chosen rest" column that is never judged. YouTube drift is the only thing the guilt trip targets.
- **No streaks.** Every designer, including the Maximalist in critique, agreed that a broken streak turns into abandonment.
- **The vault is the phone bus.** Today, Week and Inbox notes in Obsidian reach your phone for free.
- **Garmin must show when it might be wrong.** The Coach's trust badges plus a one-tap "how do you feel" fallback.
- **One global notification budget.** Six designs adding up their own pings would hit about 10 a day. Cap the total.

---

## What I'm keeping (v1 core)

| Feature | From | Why it earns its place |
|---|---|---|
| **The Sentence + Next** | Minimalist | Answers "tell me what to do" in two seconds. The top of every screen. |
| **Day timeline, ink vs pencil** | Secretary | Your real day, with proposals visibly separate from facts. |
| **Proposal queue** | Maximalist + Secretary | Confirm / Edit / Decline, about 5 a day max. Learns from declines. Everything can be undone. |
| **The Call** (GO / EASY / REST) | Coach | One rules-based training verdict with a trust badge on each input. Backing off needs two independent signals. It is advice and never moves anything itself. |
| **Start-by dates** | Academic | Canvas due dates get pushed into the background. "Start Dynamics PS today" is what shows up in your day. |
| **3-week horizon strip** | Academic | A crunch week shows up 2–3 weeks early, not the night before. |
| **Job window finder + weekly target** | Secretary + Minimalist | Ranked work blocks around class and training. It never suggests gaps under about 60 minutes. Shows "9 of 14 h". |
| **Rest windows + Screen Time ledger** | Psychologist + Secretary | Chosen rest vs drift, with an opt-in roast (see Decisions). |
| **Commitments in your words** | Psychologist + Minimalist | Max 3 active by default. Each one ends as Done / Moved / **Dropped**, and dropping carries no penalty. |
| **Push level + Back-off** | Psychologist | One global setting (Quiet / Normal / Push) that you can raise for a single domain for a week. Three ignored nudges in a row automatically lowers it one step. |
| **Bad Week mode + Re-entry** | Psychologist | One tap shrinks the plan to a minimum viable day. If you've been away 3+ days, you get no backlog dump, just one easy win. |
| **Receipts rule** | Psychologist | Praise and criticism must cite a real number or date, or they don't ship. |
| **Evening close** (2 min) **+ Sunday plan** (15 min) | Secretary + everyone | The two rituals where planning happens, so the rest of the day can stay quiet. |
| **Chat drawer** (Claude / local) | your plan | A model toggle you asked for. It can read the same data. It's a drawer, not the home screen. |
| **Source health footer + cold-start mode** | missed by most | Shows "Garmin synced 6:31" and "learning, 3 samples". Turns silent failures into honest ones. |
| **Semester rollover** | Academic | Courses come from Canvas each term. A 10-minute pre-filled setup in week 1. Nothing is hard-coded. |

---

## Next (v2), once v1 survives a month

- **One Log:** your weight tracker migrated in, sharing a timeline with training. Shown as a 7-day average with a bulk-pace corridor, and only when you open it. I'm moving this up as soon as you're ready to migrate, because the Coach is right that the app can't know the bulk exists without it.
- **Summit Windows:** 14er go/no-go with a turnaround time, a taper the days before, a winter/CAIC mode, and a trip-plan note to share with someone for solo days.
- **Goal ladders:** half marathon, 5K, bench, RDL, muscle-up, each with its next rung and an honest "stalled" flag.
- **Interference rules:** no heavy lower-body work within 24 h before a quality run, and soccer counts as load.
- **Duration estimator:** learns how long tasks take, mostly passively (it infers from the calendar and you confirm at evening close). Quotes the P75 time, not the hopeful one. Start/Done timers are optional.
- **Syllabus ingest:** paste or drop a PDF and confirm before saving. Canvas usually lacks exam dates and weights, and crunch warnings are wrong without them.
- **Application pipeline in the vault:** stages, stall notes ("Drafted for 9 days"), and day-2 / day-7 follow-up reminders.
- **Email "needs reply" + deadlines**, via Apple Mail's local store (see Feasibility).
- **Rest quality tap:** Restored / Meh / Drained, optional. It tests whether your switch from YouTube to Netflix and Minecraft is actually working.
- **"Why" card:** reasons you wrote yourself, shown on bad weeks instead of generated pep.
- **Dismissal self-audit:** the app quietly retires whichever nudges you ignore most.

## Later / parking lot

These are fine ideas, but none is worth building before the core is a habit:
- Vault search (RAG)
- Active-recall queue (opt-in per course, with a "declare bankruptcy" button)
- Grade math and the 4+1 pathway tracker (on demand only)
- Interview prep packets
- Lift progression
- Skill-practice snacks in class gaps
- 3D printer status
- Résumé bullet bank
- A monthly "pattern hypothesis" (requires n ≥ 10, labeled as a guess)

---

## What I cut, and why

You asked for this explicitly, so here it is in full.

**Cut: cross-source "insight" engine** (Maximalist's Signal Engine). It would produce lines like "your 4 shortest sleeps followed late Minecraft." With one person's data, those are mostly coincidences delivered with confidence, and that one would undercut the rest switch you chose on purpose. It's replaced by a few hand-written rules. Maybe a monthly hypothesis later.

**Cut: predicted energy curve** (Maximalist, Psychologist). This draws a precise-looking hourly curve from Body Battery, which is the least reliable number on the watch. Hard work goes where you've actually finished hard work before, not where a curve says it should.

**Cut: real-time doomscroll interceptors** (Maximalist's interceptor, Psychologist's "doors" and redirect). Each needs a background agent watching which app you have open. They're fragile across macOS updates, they fire at your least receptive moments, and you already fixed the worst case by deleting Instagram. After-the-fact Screen Time is enough.

**Cut: mandatory Start/Done timers** (Secretary). These build the tool on a habit you don't have yet. The Secretary listed this as her own top risk. Kept as optional.

**Cut: calorie and food-correction features** (Coach's "trim 150 kcal" guard, protein and meal scoreboards, weigh-in annotations about dinner). Unsolicited comments on food and body composition are a short step from obsessive tracking. Weight stays as data you choose to look at.

**Cut: streaks and scoreboards** (Maximalist's Streaks & Commitments, Coach's consistency scoreboard). The first miss turns them red, and then you stop opening the app. The Psychologist's 28-day "cairn" is the forgiving version, but I'm leaving even that out of v1 as decoration.

**Cut: standing GPA and pathway widget** (Academic). A number that's always on screen is background stress, and it changes once a semester. Available on demand instead.

**Cut: one sentence as the *whole* app** (Minimalist). It's perfect as the top layer. As the only layer it would say "nothing needs you" 13 days before a midterm. The Academic's horizon strip fixes that.

**Cut: location tracking for walk times** (Secretary). A privacy and permissions cost for a number you can type once. It uses a default 10-minute buffer you can edit.

**Cut: midday "you're 25 min behind" nudges** (Secretary). These make the plan a supervisor and add stress. Re-planning happens quietly at evening close unless a hard deadline is at risk.

**Cut: Mines email via a direct Microsoft login** (Maximalist, Secretary). The school tenant likely blocks it, and it was the highest-effort, most fragile source. Apple Mail replaces it (see Feasibility).

**Cut: personas** ("Ask Rhys", "Dexter is disappointed"). One assistant with one voice that you edit in a `voice.md` file in your vault.

**Cut: a 5 × 4 grid of per-domain push dials** (Psychologist). A settings screen you'd configure once and forget. Replaced by one global setting plus a temporary per-domain boost.

**Cut: roasts that link screen time to HRV** (Maximalist). Same spurious-causation problem as the insight engine.

**Cut: auto-swapping your day on low recovery** (Academic, Coach). Kept as a suggestion you accept, never a silent change.

**Cut: hard "won't schedule after 11 pm" wall** (Academic). Kept as a warning, because sometimes there's a real deadline.

**Cut: filler** (Maximalist's snow-day ranker, PR hunter, project pulse, spoken mock interviews). None has a confirmed data source or a real need right now.

**Cut: ntfy as a default** (Maximalist). It's free, but your notification topic is only private if nobody guesses the name, and the Reminders route below does the job without a third party. Kept as an optional extra.

---

## Decisions only you can make

My recommendation is listed first in each. Tick or rewrite.

1. **Default density.**
   - [ ] Sentence on top, with your day and a few cards below *(rec)*
   - [ ] Full cockpit
   - [ ] Sentence only
2. **Calendar writes.**
   - [ ] Pencil → Confirm → a separate "Assistant" calendar *(rec)*
   - [ ] Some things exempt (recurring training, rest windows) after you approve them once
3. **Guilt trip.**
   - [ ] Off until you opt in, then a weekly roast plus at most one evening line when drift was notable *(rec)*
   - [ ] Daily
   - [ ] Tone: dry / playful / brutal
4. **School vs training in crunch weeks.**
   - [ ] Deadlines within 24 h beat sessions. Otherwise training is an anchor, and crunch weeks cut volume, not frequency *(rec)*
   - [ ] School always wins
5. **Can it tell you to work *less* at the job?**
   - [ ] Yes, in crunch weeks it proposes a cap *(rec)*
   - [ ] No, it only finds hours
6. **Daily input budget.**
   - [ ] 2 taps a day max (feel rating + evening close) *(rec)*
   - [ ] More if it buys better estimates
7. **Notification budget.**
   - [ ] 3 a day total on the Mac, plus whatever you pre-schedule to your phone *(rec)*
   - [ ] 2 (Minimalist)
   - [ ] 5 (Maximalist)
8. **Look.**
   - [ ] Follows macOS light/dark *(rec, both palettes)*
   - [ ] Always dark
   - [ ] Always light
9. **Name.** Minimalist and Psychologist both picked "Cairn" (the Minimalist renamed hers "Plumb" during critique). Mine is "Switchback". Your call.

---

## Phone plan (free, no email)

The key constraint: **your Mac can't send anything while it's asleep.** So the plan schedules alerts *ahead of time* in systems that sync to iCloud on their own.

1. **Apple Reminders and Calendar alerts.** These are the primary push. At morning run and evening close, the app writes time-bound Reminders ("Start Dynamics PS, 10:30") and alerts on confirmed blocks. iCloud delivers them to your iPhone, iPad and watch even with the laptop closed. Free and native.
2. **Obsidian vault.** These are for reading and capture. The app writes `Assistant/Today.md`, `Week.md` and the Sunday review. You can tick `- [ ]` boxes on your phone, and anything you append to `Assistant/Inbox.md` on your phone is picked up on the Mac's next run.
3. **iMessage to yourself.** This is optional, for the rare "weather window closing" alert. The Mac can send it through Messages with AppleScript at no cost, but only while it's awake and online.
4. **ntfy.** Optional, off by default (see Cut list).

## Making it feel like a real Mac app

- **Engine:** Python, which you already know and which already has your morning brief and weight scripts. It runs collectors, rules, a local SQLite store and the model router as a `launchd` background service. It runs heavier local-model passes only when the Mac is plugged in.
- **Shell:** a thin native wrapper around an HTML UI, so it has a Dock icon, a menu-bar item showing the current block and the next sentence, real actionable notifications, and a ⌥Space quick-capture. Tauri or a small SwiftUI wrapper both work; we pick at build time.
- **Fully offline:** Qwen3 through Ollama, cached data, and system fonts. Claude handles the Sunday plan and the chat when you're online, and logs its token use.
- **Waking up:** `launchd` doesn't run while the lid is closed. On wake it catches up, and a 6:25 `pmset` wake can run the morning pass when the Mac is plugged in.

## Feasibility notes (checked today)

- **Garmin:** The community `python-garminconnect` library now uses the same login flow as the Garmin mobile app. It supports MFA and caches and refreshes its tokens. It exposes sleep, HRV, training readiness, training load and activities, and it can also record weigh-ins. The risk is that it's unofficial and can break, so cache everything and fall back to the feel tap. ([repo](https://github.com/cyberjunky/python-garminconnect))
- **Screen Time:** Mac usage can be read from `knowledgeC.db`. iPhone and iPad usage arrives through iCloud's Biome store when "Share across devices" is on. Both need Full Disk Access, and with launchd the Python binary itself must be granted it. Expect fiddling after macOS updates. ([example](https://github.com/nichtlegacy/screentime))
- **Email:** Add iCloud, Gmail and Mines to Apple Mail, then read Mail's local store. That's one path for all three, it works on cached mail offline, and it avoids Microsoft's login entirely.
- **ntfy:** The public server is free and supports action buttons. Treat topic names as public. ([overview](https://themenonlab.blog/blog/ntfy-free-push-notifications))

---

## Build order

**Phase 0, a weekend.** Python engine and SQLite. Calendar/Reminders (EventKit), Canvas and weather collectors. The Today view with the Sentence and timeline, Mac notifications, the chat drawer, and `Today.md` in the vault. *Bring in one new source per week after this, so setup failures don't pile up.*

**Phase 1, weeks 1–3.** Garmin and The Call with trust badges. Pencil/ink proposals and the separate calendar. Start-by dates and the horizon strip. Job window finder. Evening close and the Sunday plan. Push level, Back-off and Bad Week mode. The source health footer.

**Phase 2, weeks 4–8.** Screen Time, rest windows and the opt-in roast. Commitments. Weight tracker migration into One Log. Summit Windows. Apple Mail "needs reply".

**Phase 3.** The estimator, syllabus ingest, the application pipeline, and whatever you're still asking for in week 8.

**Kill test:** if you aren't opening it on most days by week 6, cut features rather than add them.

---

## Mockups

There are seven: one from each designer plus mine (Switchback), all in one gallery to flip through. What each one taught:

- **Plumb (Minimalist):** the empty state. "Nothing else needs you" is the best line anyone wrote.
- **Summit Ops (Maximalist):** proposals as ghost blocks on the timeline, and insight cards that show their sources. Too dense to glance at.
- **Quire (Academic):** the semester strip is the strongest single visual in the set. Too text-heavy for the morning.
- **Basecamp (Coach):** the verdict with a visible "why" and trust badges. Mostly a training app.
- **Cairn (Psychologist):** the letter-style note with data chips, and rest drawn as a protected block. Prose takes longer to scan.
- **The Ledger (Secretary):** ink vs pencil, the cleverest device. Reads like a planner.
- **Switchback (mine):** the synthesis. The Sentence and Next up top, then the 3-week strip, an ink/pencil day, The Call, job hours, rest, and commitments, with a chat drawer and a source footer. Works offline with system fonts and follows light/dark mode.
