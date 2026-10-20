"""Deterministic rules: given the day's blocks and the clock, decide The Sentence.

No model involved. Everything shown cites a number or time from the data (receipts).
The day itself is demo data (data/demo_day.json, or the fake sample) until the
Calendar and Canvas collectors exist.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from meliora import config


@dataclass
class Block:
    id: str
    start: float  # hours since midnight, e.g. 15.25 = 3:15 pm
    end: float
    kind: str  # ink | pen | prot | rest
    title: str
    sub: str
    where: str = ""
    deadline_hours: float = 0.0  # hours this block puts toward the day's deadline

    @property
    def hours(self) -> float:
        return self.end - self.start


@dataclass
class Day:
    blocks: list[Block]
    deadline: dict  # name, short, due, due_day, estimate_h (P75)
    job: dict = field(default_factory=lambda: {"target_h": 0, "done_h": 0})


def demo_day() -> Day:
    raw = json.loads(config.find("demo_day.json").read_text())
    return Day([Block(**b) for b in raw["blocks"]], raw["deadline"], raw.get("job", {}))


def fmt(h: float, ampm: bool = True) -> str:
    hh, mm = int(h), round((h - int(h)) * 60)
    s = f"{(hh - 1) % 12 + 1}:{mm:02d}"
    return f"{s} {'am' if hh < 12 else 'pm'}" if ampm else s


def fmt_dur(h: float) -> str:
    m = round(h * 60)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def decide(day: Day, decisions: dict[str, str], now: datetime) -> dict:
    blocks, dl = day.blocks, day.deadline
    t = now.hour + now.minute / 60
    for b in blocks:
        if b.kind == "pen" and decisions.get(b.id) == "confirm":
            b.kind = "ink"
    live = [b for b in blocks if decisions.get(b.id) != "decline"]
    actionable = [b for b in live if b.kind in ("ink", "pen") and b.end > t]
    current = next((b for b in actionable if b.start <= t), None)
    upcoming = [b for b in actionable if b.start > t]
    nxt = upcoming[0] if upcoming else None

    ps_planned = sum(b.deadline_hours for b in live)
    ps_short = dl["estimate_h"] - ps_planned

    # Rule 1: a deadline inside 72 h with unplanned hours beats everything.
    if ps_short > 0:
        sentence = (
            f"{dl['name']} is <mark>{fmt_dur(ps_short)} short</mark>. "
            f"It's due {dl['due_day']}, so find that time before then."
        )
        because = [f"{dl['short']} · due {dl['due']}", f"P75 est. {fmt_dur(dl['estimate_h'])}",
                   f"planned {fmt_dur(ps_planned)}"]
    # Rule 2: otherwise, the next thing on the timeline.
    elif nxt:
        lead = "Then start" if current else "Start"
        sentence = f"{lead} {nxt.title} at <mark>{fmt(nxt.start, ampm=False)}</mark>."
        if nxt.deadline_hours:
            sentence += f" It's due {dl['due_day']}, and today is your last open runway."
        because = [f"{fmt(nxt.start)}–{fmt(nxt.end)}", nxt.sub]
        if current:
            because.insert(0, f"now: {current.title} until {fmt(current.end)}")
    elif current:
        sentence = f"Finish {current.title}. It runs until <mark>{fmt(current.end, ampm=False)}</mark>."
        because = [f"ends {fmt(current.end)}", "nothing else after it"]
    else:
        sentence = "Nothing else needs you today. <mark>Rest is the plan.</mark>"
        because = ["0 blocks left", f"{fmt_dur(ps_planned)} of {dl['short']} planned"]

    job = blocks_by_id(blocks).get("job")
    job_state = decisions.get("job", "pending")

    return {
        "date": now.strftime("%A, %B ") + str(now.day),
        "now": t,
        "sentence": sentence,
        "because": because,
        "next": next_card(nxt or current, t),
        "blocks": [asdict(b) | {"decision": decisions.get(b.id, "")} for b in blocks],
        "job": {"done": day.job.get("done_h", 0), "target": day.job.get("target_h", 0),
                "extra": 0 if job_state == "decline" or not job else job.hours, "state": job_state},
        "pending": sum(1 for b in blocks if b.kind == "pen" and b.id not in decisions),
    }


def blocks_by_id(blocks: list[Block]) -> dict[str, Block]:
    return {b.id: b for b in blocks}


def next_card(b: Block | None, t: float) -> dict | None:
    if not b:
        return None
    label = "Now" if b.start <= t else "Next"
    return {"label": f"{label} · {fmt(b.start)}" + (f", {b.where}" if b.where else ""),
            "what": b.title, "meta": b.sub, "pencil": b.kind == "pen"}
