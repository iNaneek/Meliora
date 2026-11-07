"""The Ask drawer: questions about today, answered by a local model or by Claude.

On-device (Qwen3): a compact briefing built by Python (today's schedule, weather, body
numbers), and it answers from that alone. It describes; it never makes training calls.

Claude (Haiku / Sonnet / Opus, online): the same briefing plus the body data (last 3 weeks
of daily numbers and recent activities) and the calendar for the next week. It can give
training advice, and it can propose calendar events. Proposals are pencil: they're drawn
dashed and written to the "Meliora" calendar only when Keenan confirms. No memory: each
drawer conversation starts fresh, and nothing about it is kept for later questions.
"""

import re
from datetime import date, datetime, timedelta

from meliora import body, calendars, db, llm, overview, proposals, rules, weather

MAX_TURNS = 6  # earlier messages are dropped so the prompt fits the 4k context

SYSTEM = """You are Meliora, a personal assistant on Keenan's Mac. Answer questions about his day using only the briefing below.
- Be brief: one to four sentences. Plain text, no markdown, no lists unless asked.
- Use the numbers, times and dates from the briefing. If the briefing doesn't have it, say so plainly. Never invent data.
- Body numbers: describe them (how they compare with his usual range). Do not make training calls or suggest workouts, rest, or recovery; say training calls come from the weekly plan.
- "pencil" blocks are proposed and not confirmed yet; "ink" blocks are fixed; "protected" and "rest" blocks are chosen downtime and are never judged.

Briefing:
{briefing}"""


def _fmt_h(h: float) -> str:
    return rules.fmt(h)


def briefing(now: datetime | None = None) -> str:
    now = now or datetime.now()
    day = rules.today_day(now)
    state = rules.decide(day, db.decisions(now.date().isoformat()), now)
    lines = [f"Now: {now:%A, %B} {now.day}, {_fmt_h(state['now'])}"]
    nxt = state["next"]
    if nxt:
        lines.append(f"Next up: {nxt['what']} ({nxt['label']})")
    lines.append("Today's schedule:")
    for b in state["blocks"]:
        kind = {"ink": "ink", "pen": "pencil", "prot": "protected", "rest": "rest", "del": "ink, proposed for deletion"}.get(b["kind"], b["kind"])
        status = " (declined)" if b["decision"] == "decline" else " (confirmed)" if b["decision"] == "confirm" else ""
        sub = f", {b['sub']}" if b["sub"] and b["sub"] != "protected" else ""
        lines.append(f"- {_fmt_h(b['start'])}-{_fmt_h(b['end'])} {b['title']} [{kind}{status}]{sub}")
    if day.all_day:
        lines.append("All day: " + "; ".join(day.all_day))
    if day.deadline:
        d = day.deadline
        est = f", about {d['estimate_h']:g} h of work" if d.get("estimate_h") else ""
        lines.append(f"Main deadline: {d.get('name')}, due {d.get('due', '')}{est}")
    if day.job.get("target_h"):
        lines.append(f"Job hours this week: {day.job.get('done_h', 0):g} of {day.job['target_h']:g} h")
    w = weather.today_line()
    if w:
        lines.append(f"Weather today: {w.get('high_f')}°F high, {w.get('low_f')}°F low, {w.get('sky', '')}"
                     + (f", {w['precip']}" if w.get("precip") else ""))
    f = overview.facts()
    if f:
        lines.append(f"Body (Garmin, as of {f['as_of']}):")
        lines += [f"- {line}" for line in overview._fact_lines(f)]
    return "\n".join(lines)


# "Should I run today?" is a training call. Rules decide those, not an on-device model,
# so these get a plain answer: what today's plan already says.
_TRAINING_Q = re.compile(
    r"\b(should|can|could|ok|okay|fine|safe|smart|good idea|worth)\b.*\b(run|running|train|training|lift|lifting|"
    r"climb|climbing|hike|hiking|workout|work out|exercise|rest|skip|push|go hard|take it easy)\b", re.I)
_TRAINING_BLOCK = re.compile(r"\b(run|lift|climb|hike|workout|ride|swim|gym|strength)\b|The Call", re.I)


def _training_answer(now: datetime) -> str:
    state = rules.decide(rules.today_day(now), db.decisions(now.date().isoformat()), now)
    plan = [b for b in state["blocks"] if _TRAINING_BLOCK.search(f"{b['title']} {b['sub']}")
            and b["decision"] != "decline"]
    lead = "Training calls aren't made on-device; they come from the weekly plan."
    if not plan:
        return lead + " Nothing training-related is on today's plan."
    items = "; ".join(f"{b['title']} at {_fmt_h(b['start'])}" + (f" ({b['sub']})" if b["sub"] else "") for b in plan)
    return f"{lead} Today's plan has: {items}. Your body numbers are on the Body page."


def answer(question: str, history: list[dict], tier: str = "fast") -> dict:
    """history: earlier turns as [{"role": "user"|"assistant", "content": str}, ...]."""
    if _TRAINING_Q.search(question):
        return {"ok": True, "text": _training_answer(datetime.now()), "model": "rules", "ms": 0}
    turns = [m for m in history if m.get("role") in ("user", "assistant") and m.get("content")][-MAX_TURNS:]
    messages = [{"role": "system", "content": SYSTEM.format(briefing=briefing())}, *turns,
                {"role": "user", "content": question}]
    try:
        text, info = llm.local_text("ask", messages, tier)
    except llm.Unavailable as e:
        return {"ok": False, "text": f"The on-device model couldn't answer ({e})."}
    return {"ok": True, "text": text, **info}


if __name__ == "__main__":
    print(briefing())


# ---------- Claude ----------

CLAUDE_TURNS = 8
CAL_DAYS = 8         # today + the next 7 days
BODY_DAYS = 21
ACT_DAYS = 28
# metric column, header
DAILY = [("sleep_h", "sleep_h"), ("sleep_score", "sleep_score"), ("hrv_night_ms", "hrv_ms"), ("rhr", "rhr"),
         ("bb_wake", "bb_wake"), ("readiness", "readiness"), ("steps", "steps"), ("intensity_min", "intensity_min")]

CLAUDE_SYSTEM = """You are Meliora, the personal assistant in Keenan's Mac app. Keenan is a Colorado School of Mines mechanical engineering sophomore with a flexible virtual job; he runs, lifts, and climbs 14ers. He lives in Golden, CO (America/Denver time).

How to answer:
- Short and direct: one to five sentences, plain text, no markdown headings. A short list is fine when he asks for options or a plan.
- Use only the data below for facts about his day, calendar and body. If it isn't there, say so. Never invent numbers or events.
- Receipts: any praise, criticism or insight must cite a real number or date from the data. If it can't, leave it out.
- Netflix and Minecraft are chosen rest and are never judged. No calorie talk, no streaks.
- Training advice is welcome from you. Ground it in the body data and the week's calendar.

Calendar events:
- You can propose events by putting them in "events" (local time, ISO 8601 without a time zone, e.g. 2026-11-08T07:00). Use "location" only if known, else "".
- Propose events only when he asks you to add or schedule something, or clearly says yes to a suggestion. Otherwise "events" is [].
- Adds and deletes are pencil: they show up dashed with Confirm / Skip, and nothing is added to his calendar until he confirms. Say so briefly in "reply" ("Proposed ..., confirm it below.") and never claim it's already added.
- Avoid overlapping existing events unless he asks for that time. If something is in the way, mention it and pick the nearest free slot. If the request is too vague to place (no day or length), ask instead of guessing.
- You can propose deleting existing events by putting their [ref] (e.g. "e12") in "delete". Only events with a ref can be deleted; ones marked read-only can't (he'd delete those in Calendar). Deleting a repeating event removes only that day.
- Propose a delete only when he asks to remove, cancel or move something. To move an event, delete it and add the new time. Deletes are pencil too: say "confirm below", never that it's gone.

{context}"""

CLAUDE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "delete": {"type": "array", "items": {"type": "string"}},
        "events": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
                           "location": {"type": "string"}},
            "required": ["title", "start", "end"]}},
    },
    "required": ["reply", "events", "delete"],
}


def _clock(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").lower()


def calendar_lines(now: datetime, refs: dict | None = None) -> list[str]:
    """One line per event. Editable events get a [ref] the model can name to delete them;
    `refs` is filled with ref -> event row."""
    if not calendars.connected():
        return ["(Apple Calendar isn't connected; only today's demo plan above is known.)"]
    refs = {} if refs is None else refs
    events = calendars.range_events(now.date(), CAL_DAYS)
    pend = proposals.pending(action="add")
    deleting = {p["target"] for p in proposals.pending(action="delete")}
    out = []
    for i in range(CAL_DAYS):
        d = now.date() + timedelta(days=i)
        lo = datetime.combine(d, datetime.min.time())
        items = []
        for e in events:
            s, en = datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])
            if not (s < lo + timedelta(days=1) and en > lo):
                continue
            where = ", ".join(" ".join(x.split()) for x in (e["calendar"], e["location"]) if x)
            if e["id"] in deleting:
                tag = "PROPOSED FOR DELETION, not confirmed yet"
            elif e["editable"] and s >= now - timedelta(hours=1):
                ref = next((r for r, row in refs.items() if row["id"] == e["id"]), None)
                if not ref:
                    ref = f"e{len(refs) + 1}"
                    refs[ref] = e
                tag = ref
            else:
                tag = "read-only" if not e["editable"] else "past"
            if e["all_day"]:
                items.append(f"  [{tag}] all day: {e['title']} ({where})")
            else:
                items.append(f"  [{tag}] {_clock(s)}-{_clock(en)} {e['title']} ({where})")
        for p in pend:
            s, en = datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"])
            if s.date() == d:
                items.append(f"  {_clock(s)}-{_clock(en)} {p['title']} (PROPOSED, not confirmed yet)")
        out.append(f"{d:%a %b} {d.day}:" + ("" if items else " nothing"))
        out += items
    return out


def body_lines() -> list[str]:
    with db.session() as conn:
        found = body.find_anchor(conn)
        if not found:
            return ["(No body data yet.)"]
        src, anchor = found
        start = (anchor - timedelta(days=BODY_DAYS - 1)).isoformat()
        vals: dict[str, dict[str, float]] = {}
        for metric, day, value in conn.execute(
                "SELECT metric, day, value FROM metrics WHERE source = ? AND day >= ? AND day <= ?",
                (src, start, anchor.isoformat())):
            vals.setdefault(day, {})[metric] = value
        acts = conn.execute(
            "SELECT start, type, name, distance_m, duration_s, elev_gain_m, avg_hr FROM activities"
            " WHERE source = ? AND start >= ? ORDER BY start",
            (src, (anchor - timedelta(days=ACT_DAYS)).isoformat())).fetchall()
        vo2 = conn.execute("SELECT day, value FROM metrics WHERE source = ? AND metric = 'vo2max'"
                           " ORDER BY day DESC LIMIT 1", (src,)).fetchone()
    out = [f"Daily numbers ({src}, sleep is for the night ending that day), oldest first:",
           "date," + ",".join(h for _, h in DAILY)]
    for i in range(BODY_DAYS):
        d = (anchor - timedelta(days=BODY_DAYS - 1 - i)).isoformat()
        row = vals.get(d, {})
        cells = [("" if m not in row else f"{row[m]:.1f}" if m == "sleep_h" else f"{row[m]:.0f}") for m, _ in DAILY]
        out.append(d + "," + ",".join(cells))
    if vo2:
        out.append(f"VO2 max: {vo2[1]:.0f} (as of {vo2[0]})")
    out.append(f"Activities, last {ACT_DAYS} days:")
    for st, typ, name, dist, dur, elev, hr in acts:
        bits = [st[:16].replace("T", " "), typ or "", name or ""]
        if dist:
            bits.append(f"{dist / body.M_PER_MI:.1f} mi")
        if dur:
            bits.append(f"{dur / 60:.0f} min")
        if elev:
            bits.append(f"{elev * body.FT_PER_M:.0f} ft up")
        if hr:
            bits.append(f"avg HR {hr:.0f}")
        out.append("- " + ", ".join(b for b in bits if b))
    if not acts:
        out.append("- none")
    return out


def claude_context(now: datetime | None = None, refs: dict | None = None) -> str:
    now = now or datetime.now()
    return "\n".join(["## Today", briefing(now), "", "## Calendar, next 7 days ([ref] = can be deleted)",
                      *calendar_lines(now, refs), "", "## Body", *body_lines()])


def answer_claude(question: str, history: list[dict], tier: str = "sonnet") -> dict:
    """One `claude -p` call. History is the drawer's earlier turns, sent as a transcript."""
    now = datetime.now()
    turns = [m for m in history if m.get("role") in ("user", "assistant") and m.get("content")][-CLAUDE_TURNS:]
    convo = "".join(f"{'Keenan' if m['role'] == 'user' else 'Meliora'}: {m['content']}\n" for m in turns)
    user = (f"Earlier in this conversation:\n{convo}\nNew message from Keenan: " if convo else "") + question
    refs: dict = {}
    try:
        data, info = llm.claude_json("ask", CLAUDE_SYSTEM.format(context=claude_context(now, refs)), user,
                                     CLAUDE_SCHEMA, tier)
    except llm.Stopped:
        return {"ok": False, "stopped": True, "text": "Stopped."}
    except llm.Unavailable as e:
        return {"ok": False, "text": f"Claude couldn't answer ({e}). Offline? The on-device models still work."}
    targets = [refs[r] for r in dict.fromkeys(str(x).strip("[] ") for x in data.get("delete") or []) if r in refs]
    events = (proposals.add_deletes(targets, info["model"])
              + proposals.add(proposals.clean(data.get("events"), now), info["model"]))
    text = str(data.get("reply") or "").strip() or ("Proposed below." if events else "(No answer.)")
    return {"ok": True, "text": text, "proposals": events, "backend": "claude", **info}
