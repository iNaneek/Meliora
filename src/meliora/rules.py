"""Deterministic rules: given the day's blocks and the clock, decide The Sentence.

No model involved. Everything shown cites a number or time from the data (receipts).
The day comes from Apple Calendar once it's connected (see `today_day`), otherwise from
demo data (data/demo_day.json, or the fake sample). Deadlines and job hours stay demo-only
until the Canvas collector and job tracking exist.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from meliora import config


@dataclass
class Block:
    id: str
    start: float  # hours since midnight, e.g. 15.25 = 3:15 pm
    end: float
    kind: str  # ink | pen | prot | rest | del (an event proposed for deletion)
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
    deadline: dict | None  # name, short, due, due_day, estimate_h (P75); None until Canvas
    job: dict = field(default_factory=lambda: {"target_h": 0, "done_h": 0})
    all_day: list[str] = field(default_factory=list)  # all-day event titles (not on the timeline)
    source: str = "demo"  # demo | calendar


def demo_day() -> Day:
    raw = json.loads(config.find("demo_day.json").read_text())
    return Day([Block(**b) for b in raw["blocks"]], raw["deadline"], raw.get("job", {}))


def calendar_day(day: date) -> Day:
    """Today's Apple Calendar events as fixed (ink) blocks. Times are hours since midnight,
    clipped to the day, so an event that started yesterday begins at 0. An event a model
    proposed deleting is drawn as a "del" block (its proposal's id) until confirmed or kept."""
    from meliora import calendars, proposals

    deleting = {p["target"]: p for p in proposals.pending(day, "delete")}
    midnight = datetime.combine(day, datetime.min.time())
    blocks, all_day = [], []
    for e in calendars.day_events(day):
        if e["all_day"]:
            all_day.append(e["title"])
            continue
        start = max(0.0, (datetime.fromisoformat(e["start"]) - midnight).total_seconds() / 3600)
        end = min(24.0, (datetime.fromisoformat(e["end"]) - midnight).total_seconds() / 3600)
        if end <= start:
            continue
        bid = "ev-" + hashlib.sha1(e["id"].encode()).hexdigest()[:10]
        kind, sub = "ink", e["location"] or e["calendar"]
        if e["id"] in deleting:
            p = deleting[e["id"]]
            bid, kind, sub = f"prop-{p['id']}", "del", f"delete? proposed by {proposals.short_model(p['model'])}"
        blocks.append(Block(id=bid, start=start, end=end, kind=kind, title=e["title"], sub=sub, where=e["location"]))
    return Day(blocks, None, {}, all_day, "calendar")


def proposal_blocks(day: date) -> list[Block]:
    """Events a model proposed in Ask, drawn as pencil until confirmed."""
    from meliora import proposals

    midnight = datetime.combine(day, datetime.min.time())
    out = []
    for p in proposals.pending(day, "add"):
        start = max(0.0, (datetime.fromisoformat(p["start"]) - midnight).total_seconds() / 3600)
        end = min(24.0, (datetime.fromisoformat(p["end"]) - midnight).total_seconds() / 3600)
        sub = (p["location"] + " · " if p["location"] else "") + "proposed by " + proposals.short_model(p["model"])
        out.append(Block(id=f"prop-{p['id']}", start=start, end=end, kind="pen", title=p["title"], sub=sub,
                         where=p["location"] or ""))
    return out


def today_day(now: datetime) -> Day:
    """The real calendar when it's connected, otherwise the demo day. Pending proposals from
    Ask are added on top as pencil blocks."""
    from meliora import calendars

    if calendars.connected():
        try:
            calendars.refresh()
        except Exception:  # degrade honestly: keep the last copy in SQLite
            import logging
            logging.getLogger(__name__).exception("calendar refresh failed")
        day = calendar_day(now.date())
    else:
        day = demo_day()
    day.blocks = sorted(day.blocks + proposal_blocks(now.date()), key=lambda b: b.start)
    return day


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
    ps_short = dl["estimate_h"] - ps_planned if dl else 0

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
        if nxt.deadline_hours and dl:
            sentence += f" It's due {dl['due_day']}, and today is your last open runway."
        because = [f"{fmt(nxt.start)}–{fmt(nxt.end)}", nxt.sub]
        if current:
            because.insert(0, f"now: {current.title} until {fmt(current.end)}")
    elif current:
        sentence = f"Finish {current.title}. It runs until <mark>{fmt(current.end, ampm=False)}</mark>."
        because = [f"ends {fmt(current.end)}", "nothing else after it"]
    else:
        sentence = "Nothing else needs you today. <mark>Rest is the plan.</mark>"
        because = ["0 blocks left"] + ([f"{fmt_dur(ps_planned)} of {dl['short']} planned"] if dl else [])

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
        "pending": sum(1 for b in blocks if b.kind in ("pen", "del") and b.id not in decisions),
        "source": day.source,
        "all_day": day.all_day,
    }


def blocks_by_id(blocks: list[Block]) -> dict[str, Block]:
    return {b.id: b for b in blocks}


def next_card(b: Block | None, t: float) -> dict | None:
    if not b:
        return None
    label = "Now" if b.start <= t else "Next"
    return {"label": f"{label} · {fmt(b.start)}" + (f", {b.where}" if b.where else ""),
            "what": b.title, "meta": b.sub, "pencil": b.kind == "pen"}
