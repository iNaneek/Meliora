"""Garmin collector: sleep, HRV, RHR, Body Battery, readiness, VO2 max, and activities.

Garmin's API is unofficial and rate-limited, so requests are few and deliberate:
- Each pull asks only for the endpoints below. Every response is stored raw
  (compressed) and the numbers we use are extracted into `metrics`.
- Re-pulling a day replaces that day's rows; nothing duplicates.
- Login happens once in Terminal (`uv run meliora-garmin login`). Only the session
  tokens are kept, in macOS Keychain. The password is never stored.

When the app pulls is decided in `auto_pull` (see the policy there).
"""

import argparse
import getpass
import json
import logging
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone

import keyring

from meliora import config, db

SOURCE = "garmin"
KEYRING_SERVICE = "meliora-garmin"
KEYRING_USER = "tokens"
AUTO_MAX = 3                 # automatic pulls per calendar day
RETRY_AFTER = timedelta(minutes=30)
BACKFILL_PAUSE_S = 2.0       # between requests when backfilling, to stay polite

log = logging.getLogger(__name__)
_lock = threading.Lock()     # one pull at a time (auto, button, or backfill)


class NotConnected(Exception):
    """No saved Garmin login yet."""


# ---------- session ----------

def _client():
    from garminconnect import Garmin  # imported lazily: slow, and only needed when pulling

    tokens = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if not tokens:
        raise NotConnected("Run `uv run meliora-garmin login` once in Terminal.")
    api = Garmin()
    api.login(tokenstore=tokens)
    _save_tokens(api)  # tokens may have been refreshed during login
    return api


def _save_tokens(api) -> None:
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, api.client.dumps())


def connected() -> bool:
    return bool(keyring.get_password(KEYRING_SERVICE, KEYRING_USER))


def login() -> None:
    from garminconnect import Garmin

    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password (not saved): ")
    api = Garmin(email, password, prompt_mfa=lambda: input("MFA code: ").strip())
    api.login()
    _save_tokens(api)
    print(f"Logged in as {api.get_full_name()}. Tokens saved to Keychain ({KEYRING_SERVICE}).")


# ---------- extraction: raw response → metrics ----------
# Field names follow Garmin's JSON. If one is wrong or missing, nothing breaks: the raw
# response is kept, so fix the mapping here and run `meliora-garmin reextract`.

def _dig(d, *path):
    for k in path:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int) and len(d) > k:
            d = d[k]
        else:
            return None
    return d


def _clock_h(ms):
    """Garmin local timestamp (ms) → hour of day as a float, e.g. 22.75."""
    if not ms:
        return None
    t = datetime.fromtimestamp(ms / 1000, timezone.utc)  # "Local" stamps already hold local wall time
    return round(t.hour + t.minute / 60, 2)


def _hours(sec):
    return round(sec / 3600, 2) if sec else None


def extract(conn, endpoint: str, day: str, data) -> None:
    put = lambda m, v, unit: db.put_metric(conn, m, day, v, unit, SOURCE)
    if endpoint == "sleep":
        s = _dig(data, "dailySleepDTO") or {}
        put("sleep_h", _hours(s.get("sleepTimeSeconds")), "h")
        put("sleep_deep_h", _hours(s.get("deepSleepSeconds")), "h")
        put("sleep_rem_h", _hours(s.get("remSleepSeconds")), "h")
        put("sleep_awake_min", round(s["awakeSleepSeconds"] / 60) if s.get("awakeSleepSeconds") else None, "min")
        put("sleep_score", _dig(s, "sleepScores", "overall", "value"), "score")
        put("bed_time", _clock_h(s.get("sleepStartTimestampLocal")), "clock_h")
        put("wake_time", _clock_h(s.get("sleepEndTimestampLocal")), "clock_h")
    elif endpoint == "hrv":
        put("hrv_night_ms", _dig(data, "hrvSummary", "lastNightAvg"), "ms")
        put("hrv_week_ms", _dig(data, "hrvSummary", "weeklyAvg"), "ms")
    elif endpoint == "summary":
        put("rhr", data.get("restingHeartRate"), "bpm")
        put("steps", data.get("totalSteps"), "steps")
        put("bb_wake", data.get("bodyBatteryAtWakeTime"), "bb")
        put("bb_high", data.get("bodyBatteryHighestValue"), "bb")
        put("bb_low", data.get("bodyBatteryLowestValue"), "bb")
        mod, vig = data.get("moderateIntensityMinutes"), data.get("vigorousIntensityMinutes")
        if mod is not None or vig is not None:
            put("intensity_min", (mod or 0) + 2 * (vig or 0), "min")  # Garmin counts vigorous double
    elif endpoint == "readiness":
        rows = [r for r in (data or []) if isinstance(r, dict)]
        morning = [r for r in rows if r.get("inputContext") == "AFTER_WAKEUP_RESET"]
        pick = (morning or sorted(rows, key=lambda r: r.get("timestamp") or ""))[:1]
        if pick:
            put("readiness", pick[0].get("score"), "score")
    elif endpoint == "max_metrics":
        g = _dig(data, 0, "generic") or {}
        put("vo2max", g.get("vo2MaxPreciseValue") or g.get("vo2MaxValue"), "ml/kg/min")


def save_activities(conn, acts: list[dict]) -> int:
    for a in acts:
        conn.execute(
            """INSERT OR REPLACE INTO activities
               (id, source, start, type, name, distance_m, duration_s, elev_gain_m, avg_hr, max_hr)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"{SOURCE}:{a.get('activityId')}", SOURCE, (a.get("startTimeLocal") or "").replace(" ", "T"),
             _dig(a, "activityType", "typeKey"), a.get("activityName"), a.get("distance"),
             a.get("duration"), a.get("elevationGain"), a.get("averageHR"), a.get("maxHR")),
        )
        db.put_raw(conn, SOURCE, "activity", str(a.get("activityId")), json.dumps(a))
    return len(acts)


# ---------- pulling ----------

def _fetch(api, conn, endpoint: str, day: date):
    calls = {
        "sleep": api.get_sleep_data, "hrv": api.get_hrv_data, "summary": api.get_user_summary,
        "readiness": api.get_training_readiness, "max_metrics": api.get_max_metrics,
    }
    key = day.isoformat()
    data = calls[endpoint](key)
    db.put_raw(conn, SOURCE, endpoint, key, json.dumps(data))
    extract(conn, endpoint, key, data or {})
    return data


def _last_activity_day(conn) -> date | None:
    row = conn.execute("SELECT MAX(start) FROM activities WHERE source = ?", (SOURCE,)).fetchone()
    return date.fromisoformat(row[0][:10]) if row[0] else None


def pull(first_of_day: bool = False) -> dict:
    """One pull. Today's sleep/HRV/summary/readiness, plus activities since the last one.
    First pull of the day also finalizes yesterday (summary + VO2 max). Returns a report."""
    today = date.today()
    with _lock:
        api = _client()
        with db.session() as conn:
            try:
                sleep = _fetch(api, conn, "sleep", today)
                for ep in ("hrv", "summary", "readiness"):
                    _fetch(api, conn, ep, today)
                if first_of_day:
                    for ep in ("summary", "max_metrics"):
                        _fetch(api, conn, ep, today - timedelta(days=1))
                since = min(_last_activity_day(conn) or today, today - timedelta(days=1))
                n_acts = save_activities(conn, api.get_activities_by_date(since.isoformat(), today.isoformat()))
            finally:
                _save_tokens(api)
            sleep_ok = bool(_dig(sleep, "dailySleepDTO", "sleepTimeSeconds"))
            db.mark_sync(conn, SOURCE, True, "sleep ok" if sleep_ok else "waiting on sleep")
    return {"sleep_ok": sleep_ok, "activities": n_acts}


def auto_pull(reason: str) -> dict | None:
    """Called on app launch, Mac wake, and the retry timer. The policy:
    - The first call of a calendar day pulls.
    - If last night's sleep hasn't synced, retry 30 and 60 min later.
    - At most 3 automatic pulls a day, then stop. The Sync button is separate and uncapped.
    Returns the pull report, or None when nothing was due."""
    if not connected():
        return None
    today = date.today().isoformat()
    with db.session() as conn:
        row = conn.execute("SELECT auto_count, last_try, sleep_ok FROM garmin_pulls WHERE day = ?",
                           (today,)).fetchone()
    count, last_try, sleep_ok = row or (0, None, 0)
    if count >= AUTO_MAX or sleep_ok:
        return None
    if last_try and datetime.now() - datetime.fromisoformat(last_try) < RETRY_AFTER - timedelta(minutes=1):
        return None
    log.info("garmin auto pull %d/%d (%s)", count + 1, AUTO_MAX, reason)
    try:
        report = pull(first_of_day=count == 0)
        counted = True
    except Exception as e:
        from garminconnect import GarminConnectConnectionError, GarminConnectTooManyRequestsError

        # Offline doesn't use up a slot. Rate-limited does, and stops the day.
        counted = isinstance(e, GarminConnectTooManyRequestsError) or not isinstance(e, GarminConnectConnectionError)
        if isinstance(e, GarminConnectTooManyRequestsError):
            count = AUTO_MAX - 1
        log.warning("garmin auto pull failed: %s", e)
        with db.session() as conn:
            db.mark_sync(conn, SOURCE, False, str(e)[:200])
        report = None
    with db.session() as conn:
        conn.execute(
            """INSERT INTO garmin_pulls (day, auto_count, last_try, sleep_ok) VALUES (?, ?, ?, ?)
               ON CONFLICT(day) DO UPDATE SET auto_count = excluded.auto_count,
                 last_try = excluded.last_try, sleep_ok = excluded.sleep_ok""",
            (today, count + counted, db.now(), int(bool(report and report["sleep_ok"]))),
        )
    if not (report and report["sleep_ok"]) and count + counted < AUTO_MAX:
        t = threading.Timer(RETRY_AFTER.total_seconds(), auto_pull, args=("retry",))
        t.daemon = True
        t.start()
    return report


def manual_pull() -> dict:
    """The Sync button. Uncapped, and doesn't use an auto slot. If it finds last night's
    sleep, the remaining auto retries for today are cancelled."""
    today = date.today().isoformat()
    with db.session() as conn:
        row = conn.execute("SELECT auto_count FROM garmin_pulls WHERE day = ?", (today,)).fetchone()
    report = pull(first_of_day=not row or row[0] == 0)
    with db.session() as conn:
        conn.execute(
            """INSERT INTO garmin_pulls (day, auto_count, last_try, sleep_ok) VALUES (?, 0, ?, ?)
               ON CONFLICT(day) DO UPDATE SET sleep_ok = MAX(sleep_ok, excluded.sleep_ok)""",
            (today, db.now(), int(report["sleep_ok"])),
        )
    return report


def status() -> dict:
    with db.session() as conn:
        row = conn.execute("SELECT last_ok, detail FROM source_sync WHERE source = ?", (SOURCE,)).fetchone()
    return {"connected": connected(), "last_ok": row and row[0], "detail": row and row[1],
            "busy": _lock.locked()}


# ---------- one-time jobs ----------

def backfill(since: date) -> None:
    """Fill history from `since` to yesterday. Resumable: days already stored are skipped,
    so if Garmin rate-limits it, just run it again later."""
    from garminconnect import GarminConnectTooManyRequestsError

    api = _client()
    with db.session() as conn:
        have = {(e, k) for e, k in conn.execute(
            "SELECT endpoint, key FROM raw_responses WHERE source = ?", (SOURCE,))}
    print(f"Activities since {since}…")
    with db.session() as conn:
        n = save_activities(conn, api.get_activities_by_date(since.isoformat(), date.today().isoformat()))
    print(f"  {n} activities")
    days = [since + timedelta(days=i) for i in range((date.today() - since).days)]
    endpoints = ("sleep", "hrv", "summary", "readiness", "max_metrics")
    todo = [(d, e) for d in days for e in endpoints if (e, d.isoformat()) not in have]
    print(f"{len(todo)} daily requests to make (~{len(todo) * BACKFILL_PAUSE_S / 60:.0f} min).")
    try:
        for i, (d, ep) in enumerate(todo, 1):
            with db.session() as conn:
                _fetch(api, conn, ep, d)
            if i % 25 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  {d}")
            time.sleep(BACKFILL_PAUSE_S)
    except GarminConnectTooManyRequestsError:
        print("Garmin is rate-limiting. Progress is saved; run backfill again in an hour or so.")
    finally:
        _save_tokens(api)
    with db.session() as conn:
        db.mark_sync(conn, SOURCE, True, "backfill")


def reextract() -> None:
    """Rebuild Garmin metrics and activities from the stored raw responses. No network."""
    with db.session() as conn:
        rows = list(db.raw_rows(conn, SOURCE))
        acts = [json.loads(body) for ep, _, body in rows if ep == "activity"]
        for ep, key, body in rows:
            if ep != "activity":
                extract(conn, ep, key, json.loads(body) or {})
        save_activities(conn, acts)
    print(f"Re-extracted {len(rows)} raw responses.")


def load_sample() -> None:
    """Load data-sample/garmin.json (fake) into the database as source 'sample'."""
    sample = json.loads((config.SAMPLE_DIR / "garmin.json").read_text())
    with db.session() as conn:
        conn.execute("DELETE FROM metrics WHERE source = 'sample'")
        conn.execute("DELETE FROM activities WHERE source = 'sample'")
        for m in sample["metrics"]:
            db.put_metric(conn, m["metric"], m["day"], m["value"], m["unit"], "sample")
        for a in sample["activities"]:
            conn.execute(
                """INSERT OR REPLACE INTO activities
                   (id, source, start, type, name, distance_m, duration_s, elev_gain_m, avg_hr, max_hr)
                   VALUES (:id, 'sample', :start, :type, :name, :distance_m, :duration_s, :elev_gain_m, :avg_hr, :max_hr)""",
                a,
            )
    print(f"Loaded {len(sample['metrics'])} sample metrics and {len(sample['activities'])} activities.")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(prog="meliora-garmin", description="Garmin collector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="log in once; saves session tokens to Keychain")
    sub.add_parser("pull", help="pull today now (same as the Sync button)")
    b = sub.add_parser("backfill", help="fill history (resumable)")
    b.add_argument("--since", help="YYYY-MM-DD (default: [garmin] backfill_since in the config)")
    sub.add_parser("reextract", help="rebuild metrics from stored raw responses (offline)")
    sub.add_parser("sample", help="load fake data from data-sample/garmin.json")
    sub.add_parser("logout", help="delete the saved tokens from Keychain")
    args = ap.parse_args()
    try:
        if args.cmd == "login":
            login()
        elif args.cmd == "pull":
            print(manual_pull())
        elif args.cmd == "backfill":
            since = args.since or config.load().get("garmin", {}).get("backfill_since")
            if not since:
                sys.exit("Pass --since YYYY-MM-DD or set [garmin] backfill_since in the config.")
            backfill(date.fromisoformat(since))
        elif args.cmd == "reextract":
            reextract()
        elif args.cmd == "sample":
            load_sample()
        elif args.cmd == "logout":
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            print("Garmin tokens removed from Keychain.")
    except NotConnected as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
