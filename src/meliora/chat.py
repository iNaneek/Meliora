"""The Ask drawer: quick questions about today, answered by a local model.

The model gets a compact briefing built by Python (today's schedule, weather, body
numbers) and answers from that alone. On-device models describe; they never make
training calls (that's Claude's job, later).
"""

import re
from datetime import datetime

from meliora import db, llm, overview, rules, weather

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
    state = rules.decide(rules.demo_day(), db.decisions(now.date().isoformat()), now)
    lines = [f"Now: {now:%A, %B} {now.day}, {_fmt_h(state['now'])}"]
    nxt = state["next"]
    if nxt:
        lines.append(f"Next up: {nxt['what']} ({nxt['label']})")
    lines.append("Today's schedule:")
    for b in state["blocks"]:
        kind = {"ink": "ink", "pen": "pencil", "prot": "protected", "rest": "rest"}.get(b["kind"], b["kind"])
        status = " (declined)" if b["decision"] == "decline" else " (confirmed)" if b["decision"] == "confirm" else ""
        sub = f", {b['sub']}" if b["sub"] and b["sub"] != "protected" else ""
        lines.append(f"- {_fmt_h(b['start'])}-{_fmt_h(b['end'])} {b['title']} [{kind}{status}]{sub}")
    day = rules.demo_day()
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
    state = rules.decide(rules.demo_day(), db.decisions(now.date().isoformat()), now)
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
