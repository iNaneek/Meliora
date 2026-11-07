"""Calendar events a model proposed in Ask. Pencil before ink: a proposal is only drawn
(dashed, on the timeline and in the drawer) until Keenan confirms it. Confirm writes it to
the "Meliora" calendar; Skip drops it. Nothing else writes to his calendar."""

from datetime import date, datetime, timedelta

from meliora import calendars, db

MAX_PER_ANSWER = 5
MAX_HOURS = 16
HORIZON_DAYS = 90

KEYS = ("id", "title", "start", "end", "location", "model", "status")


def clean(raw: list, now: datetime) -> list[dict]:
    """Keep only well-formed events: ISO times, end after start, a sane length, not long
    past, not far off. Anything else the model sent is dropped, not guessed at."""
    out = []
    for e in (raw or [])[:MAX_PER_ANSWER]:
        try:
            title = str(e.get("title", "")).strip()[:120]
            start = datetime.fromisoformat(str(e["start"])).replace(tzinfo=None, second=0, microsecond=0)
            end = datetime.fromisoformat(str(e["end"])).replace(tzinfo=None, second=0, microsecond=0)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if not title or end <= start or end - start > timedelta(hours=MAX_HOURS):
            continue
        if end < now - timedelta(hours=1) or start > now + timedelta(days=HORIZON_DAYS):
            continue
        out.append({"title": title, "start": start.isoformat(timespec="minutes"),
                    "end": end.isoformat(timespec="minutes"), "location": str(e.get("location") or "").strip()[:120]})
    return out


def add(events: list[dict], model: str) -> list[dict]:
    with db.session() as conn:
        for e in events:
            cur = conn.execute("INSERT INTO proposals (title, start, end, location, model, created_at)"
                               " VALUES (?, ?, ?, ?, ?, ?)",
                               (e["title"], e["start"], e["end"], e["location"], model, db.now()))
            e["id"], e["model"], e["status"] = cur.lastrowid, model, "pending"
    return events


def get(pid: int) -> dict | None:
    with db.session() as conn:
        row = conn.execute(f"SELECT {', '.join(KEYS)} FROM proposals WHERE id = ?", (pid,)).fetchone()
    return dict(zip(KEYS, row)) if row else None


def pending(day: date | None = None) -> list[dict]:
    """Pending proposals, all of them or those overlapping `day`."""
    q, args = f"SELECT {', '.join(KEYS)} FROM proposals WHERE status = 'pending'", []
    if day:
        lo = datetime.combine(day, datetime.min.time())
        q += " AND start < ? AND end > ?"
        args = [(lo + timedelta(days=1)).isoformat(), lo.isoformat()]
    with db.session() as conn:
        return [dict(zip(KEYS, r)) for r in conn.execute(q + " ORDER BY start", args)]


def confirm(pid: int) -> dict:
    """Ink it: write to the Meliora calendar. Raises PermissionError / RuntimeError on failure,
    and the proposal stays pending."""
    p = get(pid)
    if not p or p["status"] != "pending":
        raise ValueError("That proposal is gone")
    eid = calendars.add_event(p["title"], datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"]),
                              p["location"] or "", f"Added by Meliora after you confirmed ({p['model']}).")
    with db.session() as conn:
        conn.execute("UPDATE proposals SET status = 'added', event_id = ? WHERE id = ?", (eid, pid))
    calendars.refresh(force=True)
    return {**p, "status": "added"}


def skip(pid: int) -> dict:
    with db.session() as conn:
        conn.execute("UPDATE proposals SET status = 'skipped' WHERE id = ? AND status = 'pending'", (pid,))
    return get(pid) or {}


def short_model(model: str) -> str:
    m = (model or "").lower()
    return next((n.title() for n in ("haiku", "sonnet", "opus") if n in m), model or "a model")
