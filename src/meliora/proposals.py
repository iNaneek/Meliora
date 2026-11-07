"""Calendar changes a model proposed in Ask. Pencil before ink: a proposal is only drawn
(dashed, on the timeline and in the drawer) until Keenan confirms it. Nothing else writes
to his calendar.

- add: Confirm writes a new event to the "Meliora" calendar.
- delete: Confirm removes one existing event (one day of a repeating one) from its calendar.
Skip drops either."""

from datetime import date, datetime, timedelta

from meliora import calendars, db

MAX_PER_ANSWER = 5
MAX_HOURS = 16
HORIZON_DAYS = 90

KEYS = ("id", "action", "title", "start", "end", "location", "calendar", "target", "model", "status")


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
            e.update(id=cur.lastrowid, action="add", model=model, status="pending", calendar=None, target=None)
    return events


def add_deletes(rows: list[dict], model: str) -> list[dict]:
    """rows: events rows (calendars.range_events) the model asked to delete. Read-only ones,
    and ones already waiting for a delete, are dropped."""
    out = []
    with db.session() as conn:
        waiting = {r[0] for r in conn.execute(
            "SELECT target FROM proposals WHERE action = 'delete' AND status = 'pending'")}
        for e in rows[:MAX_PER_ANSWER]:
            if not e.get("editable") or e["id"] in waiting:
                continue
            cur = conn.execute("INSERT INTO proposals (action, title, start, end, location, calendar, target, model,"
                               " created_at) VALUES ('delete', ?, ?, ?, ?, ?, ?, ?, ?)",
                               (e["title"], e["start"], e["end"], e["location"], e["calendar"], e["id"], model,
                                db.now()))
            waiting.add(e["id"])
            out.append({"id": cur.lastrowid, "action": "delete", "title": e["title"], "start": e["start"],
                        "end": e["end"], "location": e["location"], "calendar": e["calendar"], "target": e["id"],
                        "model": model, "status": "pending"})
    return out


def get(pid: int) -> dict | None:
    with db.session() as conn:
        row = conn.execute(f"SELECT {', '.join(KEYS)} FROM proposals WHERE id = ?", (pid,)).fetchone()
    return dict(zip(KEYS, row)) if row else None


def pending(day: date | None = None, action: str | None = None) -> list[dict]:
    """Pending proposals, all of them or those overlapping `day`, optionally of one action."""
    q, args = f"SELECT {', '.join(KEYS)} FROM proposals WHERE status = 'pending'", []
    if action:
        q += f" AND action = '{'delete' if action == 'delete' else 'add'}'"
    if day:
        lo = datetime.combine(day, datetime.min.time())
        q += " AND start < ? AND end > ?"
        args = [(lo + timedelta(days=1)).isoformat(), lo.isoformat()]
    with db.session() as conn:
        return [dict(zip(KEYS, r)) for r in conn.execute(q + " ORDER BY start", args)]


def confirm(pid: int) -> dict:
    """Carry it out. Raises PermissionError / LookupError / RuntimeError on failure, and the
    proposal stays pending."""
    p = get(pid)
    if not p or p["status"] != "pending":
        raise ValueError("That proposal is gone")
    if p["action"] == "delete":
        calendars.delete_event(p["target"])
        with db.session() as conn:
            conn.execute("UPDATE proposals SET status = 'done' WHERE id = ?", (pid,))
        calendars.refresh(force=True)
        return {**p, "status": "done"}
    eid = calendars.add_event(p["title"], datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"]),
                              p["location"] or "", f"Added by Meliora after you confirmed ({p['model']}).")
    with db.session() as conn:
        conn.execute("UPDATE proposals SET status = 'done', event_id = ? WHERE id = ?", (eid, pid))
    calendars.refresh(force=True)
    return {**p, "status": "done"}


def skip(pid: int) -> dict:
    with db.session() as conn:
        conn.execute("UPDATE proposals SET status = 'skipped' WHERE id = ? AND status = 'pending'", (pid,))
    return get(pid) or {}


def short_model(model: str) -> str:
    m = (model or "").lower()
    return next((n.title() for n in ("haiku", "sonnet", "opus") if n in m), model or "a model")
