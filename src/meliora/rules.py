"""Deterministic rules: given the day's blocks and the clock, decide The Sentence.

No model involved. Everything shown cites a number or time from the data (receipts).
The day itself is demo data until the Calendar and Canvas collectors exist.
"""

from dataclasses import asdict, dataclass
from datetime import datetime

PS_ESTIMATE_H = 3.0  # P75 estimate for Dynamics PS 6
JOB_TARGET_H = 14
JOB_DONE_H = 7


@dataclass
class Block:
    id: str
    start: float  # hours since midnight, e.g. 15.25 = 3:15 pm
    end: float
    kind: str  # ink | pen | prot | rest
    title: str
    sub: str
    where: str = ""
    ps_hours: float = 0.0  # hours this block puts toward PS 6

    @property
    def hours(self) -> float:
        return self.end - self.start


def demo_day() -> list[Block]:
    return [
        Block("breakfast", 7.25, 7.75, "prot", "Breakfast", "protected"),
        Block("dyn", 8, 8.83, "ink", "Dynamics", "Brown W210", "Brown W210"),
        Block("thermo", 9, 9.83, "ink", "Thermo", "Marquez 126", "Marquez 126"),
        Block("ps1", 10, 12, "pen", "Dynamics PS 6, part 1", "2h of 3h", "library 3rd floor", 2),
        Block("lunch", 12, 12.67, "prot", "Lunch", "protected"),
        Block("lab", 13, 14.83, "ink", "Machine Design lab", "CTLM 102", "CTLM 102"),
        Block("job", 15.25, 17.25, "pen", "Job · best window this week", "brings you to 9 of 14 h", "desk"),
        Block("run", 17.5, 18.17, "ink", "Easy run 5 mi", "Clear Creek trail · The Call: EASY", "Clear Creek trail"),
        Block("dinner", 18.5, 19.17, "prot", "Dinner", "protected"),
        Block("ps2", 19.5, 20.5, "pen", "Dynamics PS 6, part 2", "1h, finishes the estimate", "desk", 1),
        Block("rest", 20.75, 22.5, "rest", "Rest window: Minecraft or Netflix", "protected · I won't schedule over it"),
    ]


def fmt(h: float, ampm: bool = True) -> str:
    hh, mm = int(h), round((h - int(h)) * 60)
    s = f"{(hh - 1) % 12 + 1}:{mm:02d}"
    return f"{s} {'am' if hh < 12 else 'pm'}" if ampm else s


def fmt_dur(h: float) -> str:
    m = round(h * 60)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def decide(blocks: list[Block], decisions: dict[str, str], now: datetime) -> dict:
    t = now.hour + now.minute / 60
    for b in blocks:
        if b.kind == "pen" and decisions.get(b.id) == "confirm":
            b.kind = "ink"
    live = [b for b in blocks if decisions.get(b.id) != "decline"]
    actionable = [b for b in live if b.kind in ("ink", "pen") and b.end > t]
    current = next((b for b in actionable if b.start <= t), None)
    upcoming = [b for b in actionable if b.start > t]
    nxt = upcoming[0] if upcoming else None

    ps_planned = sum(b.ps_hours for b in live)
    ps_short = PS_ESTIMATE_H - ps_planned

    # Rule 1: a deadline inside 72 h with unplanned hours beats everything.
    if ps_short > 0:
        sentence = (
            f"Dynamics PS 6 is <mark>{fmt_dur(ps_short)} short</mark>. "
            "It's due Thursday, so find that time before Wednesday night."
        )
        because = ["PS 6 · due Thu 11:59 pm", f"P75 est. {fmt_dur(PS_ESTIMATE_H)}",
                   f"planned {fmt_dur(ps_planned)}"]
    # Rule 2: otherwise, the next thing on the timeline.
    elif nxt:
        lead = "Then start" if current else "Start"
        sentence = f"{lead} {nxt.title} at <mark>{fmt(nxt.start, ampm=False)}</mark>."
        if nxt.ps_hours:
            sentence += " It's due Thursday, and today is your last open runway."
        because = [f"{fmt(nxt.start)}–{fmt(nxt.end)}", nxt.sub]
        if current:
            because.insert(0, f"now: {current.title} until {fmt(current.end)}")
    elif current:
        sentence = f"Finish {current.title}. It runs until <mark>{fmt(current.end, ampm=False)}</mark>."
        because = [f"ends {fmt(current.end)}", "nothing else after it"]
    else:
        sentence = "Nothing else needs you today. <mark>Rest is the plan.</mark>"
        because = ["0 blocks left", f"{fmt_dur(ps_planned)} of PS 6 planned"]

    job = blocks_by_id(blocks)["job"]
    job_state = decisions.get("job", "pending")

    return {
        "date": now.strftime("%A, %B ") + str(now.day),
        "now": t,
        "sentence": sentence,
        "because": because,
        "next": next_card(nxt or current, t),
        "blocks": [asdict(b) | {"decision": decisions.get(b.id, "")} for b in blocks],
        "job": {"done": JOB_DONE_H, "target": JOB_TARGET_H,
                "extra": 0 if job_state == "decline" else job.hours, "state": job_state},
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
