"""Apple Calendar (EventKit): reads every calendar; writes only to its own "Meliora" calendar.

EventKit reads the Mac's local copy of every calendar in the Calendar app (iCloud, Google,
Exchange...), so it works offline. Events for yesterday through the next 3 weeks are copied
into the `events` table, which the rest of the app reads.

Writes happen only after Keenan confirms a proposal (pencil before ink), and only into a
calendar named "Meliora", so a bad plan can be deleted in one step.

Permission: macOS asks once ("Meliora would like to access your calendars"). The prompt only
appears for the Dock app (its Info.plist says why it wants access), never under launchd.
"""

import logging
import threading
from datetime import date, datetime, timedelta

from meliora import config, db

SOURCE = "calendar"
OWN_CALENDAR = "Meliora"
DAYS_BACK = 1
DAYS_AHEAD = 21
FRESH_FOR = timedelta(minutes=2)  # Today re-reads EventKit at most this often

log = logging.getLogger(__name__)
_lock = threading.Lock()
_last_refresh: datetime | None = None

# EKAuthorizationStatus values
_STATUS = {0: "not_asked", 1: "restricted", 2: "denied", 3: "granted", 4: "write_only"}


def _ek():
    import EventKit  # lazy: only needed when the calendar is used
    return EventKit


def status() -> str:
    """not_asked | denied | restricted | write_only | granted | unavailable"""
    try:
        ek = _ek()
    except ImportError:
        return "unavailable"
    return _STATUS.get(int(ek.EKEventStore.authorizationStatusForEntityType_(ek.EKEntityTypeEvent)), "denied")


def request_access(timeout: float = 120) -> str:
    """Show macOS's permission prompt (first time only) and wait for the answer."""
    if status() != "not_asked":
        return status()
    ek = _ek()
    done = threading.Event()
    store = ek.EKEventStore.alloc().init()

    def handler(granted, error):
        if error:
            log.warning("calendar access error: %s", error)
        done.set()

    store.requestFullAccessToEventsWithCompletion_(handler)
    done.wait(timeout)
    return status()


def _excluded() -> set[str]:
    return set(config.load().get("calendar", {}).get("exclude", []))


def _dt(nsdate) -> datetime:
    return datetime.fromtimestamp(nsdate.timeIntervalSince1970())


def refresh(force: bool = False) -> int | None:
    """Copy events from EventKit into SQLite. Returns the count, or None if not allowed/skipped."""
    global _last_refresh
    if status() != "granted":
        return None
    with _lock:
        if not force and _last_refresh and datetime.now() - _last_refresh < FRESH_FOR:
            return None
        ek = _ek()
        from Foundation import NSDate

        store = ek.EKEventStore.alloc().init()  # a fresh store sees access granted after launch
        start = datetime.combine(date.today() - timedelta(days=DAYS_BACK), datetime.min.time())
        end = start + timedelta(days=DAYS_BACK + DAYS_AHEAD + 1)
        pred = store.predicateForEventsWithStartDate_endDate_calendars_(
            NSDate.dateWithTimeIntervalSince1970_(start.timestamp()),
            NSDate.dateWithTimeIntervalSince1970_(end.timestamp()), None)
        skip = _excluded()
        rows = []
        for ev in store.eventsMatchingPredicate_(pred) or []:
            cal = ev.calendar().title() if ev.calendar() else ""
            if cal in skip:
                continue
            s, e = _dt(ev.startDate()), _dt(ev.endDate())
            editable = bool(ev.calendar() and ev.calendar().allowsContentModifications())
            rows.append((f"{ev.eventIdentifier()}@{s.isoformat()}", cal, ev.title() or "(no title)",
                         s.isoformat(timespec="minutes"), e.isoformat(timespec="minutes"),
                         int(bool(ev.isAllDay())), ev.location() or "", int(editable)))
        with db.session() as conn:
            conn.execute("DELETE FROM events WHERE start >= ? AND start < ?",
                         (start.isoformat(), end.isoformat()))
            conn.executemany("INSERT OR REPLACE INTO events (id, calendar, title, start, end, all_day, location, editable)"
                             " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            db.mark_sync(conn, SOURCE, True, f"{len(rows)} events")
        _last_refresh = datetime.now()
        log.info("calendar: %d events", len(rows))
        return len(rows)


def _own_calendar(store):
    """The "Meliora" calendar, made on first use in the account new events go to (usually
    iCloud, so it reaches the phone), or On My Mac if there's no account."""
    ek = _ek()
    for cal in store.calendarsForEntityType_(ek.EKEntityTypeEvent) or []:
        if cal.title() == OWN_CALENDAR and cal.allowsContentModifications():
            return cal
    default = store.defaultCalendarForNewEvents()
    source = default.source() if default else None
    if source is None:
        source = next((s for s in store.sources() or [] if s.sourceType() == ek.EKSourceTypeLocal), None)
    if source is None:
        raise RuntimeError("no calendar account to put the Meliora calendar in")
    cal = ek.EKCalendar.calendarForEntityType_eventStore_(ek.EKEntityTypeEvent, store)
    cal.setTitle_(OWN_CALENDAR)
    cal.setSource_(source)
    ok, err = store.saveCalendar_commit_error_(cal, True, None)
    if not ok:
        raise RuntimeError(f"couldn't make the Meliora calendar: {err}")
    log.info("made the %s calendar in %s", OWN_CALENDAR, source.title())
    return cal


def add_event(title: str, start: datetime, end: datetime, location: str = "", notes: str = "") -> str:
    """Write one event to the Meliora calendar. Returns its EventKit id. Call only after a Confirm."""
    if status() != "granted":
        raise PermissionError("Calendar isn't connected")
    ek = _ek()
    from Foundation import NSDate

    with _lock:
        store = ek.EKEventStore.alloc().init()
        ev = ek.EKEvent.eventWithEventStore_(store)
        ev.setTitle_(title)
        ev.setStartDate_(NSDate.dateWithTimeIntervalSince1970_(start.timestamp()))
        ev.setEndDate_(NSDate.dateWithTimeIntervalSince1970_(end.timestamp()))
        if location:
            ev.setLocation_(location)
        if notes:
            ev.setNotes_(notes)
        ev.setCalendar_(_own_calendar(store))
        ok, err = store.saveEvent_span_commit_error_(ev, ek.EKSpanThisEvent, True, None)
        if not ok:
            raise RuntimeError(f"Calendar didn't save the event: {err}")
        return ev.eventIdentifier()


def delete_event(row_id: str) -> None:
    """Remove one occurrence (events.id = "<EventKit id>@<start>") from its calendar. A repeating
    event loses only that day. Call only after a Confirm."""
    if status() != "granted":
        raise PermissionError("Calendar isn't connected")
    ek_id, _, start_s = row_id.rpartition("@")
    start = datetime.fromisoformat(start_s)
    ek = _ek()
    from Foundation import NSDate

    with _lock:
        store = ek.EKEventStore.alloc().init()
        pred = store.predicateForEventsWithStartDate_endDate_calendars_(
            NSDate.dateWithTimeIntervalSince1970_((start - timedelta(minutes=1)).timestamp()),
            NSDate.dateWithTimeIntervalSince1970_((start + timedelta(days=1)).timestamp()), None)
        match = next((ev for ev in store.eventsMatchingPredicate_(pred) or []
                      if ev.eventIdentifier() == ek_id and abs(_dt(ev.startDate()) - start) < timedelta(minutes=1)), None)
        if match is None:
            raise LookupError("That event isn't on the calendar anymore")
        if not (match.calendar() and match.calendar().allowsContentModifications()):
            raise PermissionError(f"{match.calendar().title()} is read-only; delete it in Calendar")
        ok, err = store.removeEvent_span_commit_error_(match, ek.EKSpanThisEvent, True, None)
        if not ok:
            raise RuntimeError(f"Calendar didn't delete it: {err}")


def range_events(start: date, days: int) -> list[dict]:
    """Events overlapping [start, start + days), from SQLite, oldest first."""
    lo = datetime.combine(start, datetime.min.time())
    hi = lo + timedelta(days=days)
    with db.session() as conn:
        rows = conn.execute(
            "SELECT id, calendar, title, start, end, all_day, location, editable FROM events"
            " WHERE start < ? AND end > ? ORDER BY start", (hi.isoformat(), lo.isoformat())).fetchall()
    keys = ("id", "calendar", "title", "start", "end", "all_day", "location", "editable")
    return [dict(zip(keys, r)) for r in rows]


def day_events(day: date) -> list[dict]:
    """Events that overlap `day`, from SQLite, oldest first."""
    return range_events(day, 1)


def connected() -> bool:
    """Granted and synced at least once: Today uses the real calendar instead of the demo day."""
    if status() != "granted":
        return False
    with db.session() as conn:
        return bool(conn.execute("SELECT last_ok FROM source_sync WHERE source = ?", (SOURCE,)).fetchone())


def sync_status() -> dict:
    with db.session() as conn:
        row = conn.execute("SELECT last_ok, detail FROM source_sync WHERE source = ?", (SOURCE,)).fetchone()
    return {"access": status(), "last_ok": row and row[0], "detail": row and row[1]}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("access:", status())
    if status() == "not_asked":
        print("asking:", request_access())
    print("events:", refresh(force=True))
    for e in day_events(date.today()):
        print(e["start"][11:], e["end"][11:], e["title"], "|", e["calendar"], "| all day" if e["all_day"] else "")
