"""Data for the Body view: recovery tiles, sleep/HRV/RHR trends, weekly distance, activities.

Plain numbers only (no model). Every value carries its date so the UI can say
"as of Sep 8" instead of passing off old data as today's (receipts, degrade honestly).
Uses real Garmin rows when there are any, otherwise the fake sample (data-sample/garmin.json).
"""

from datetime import date, timedelta

from meliora import db

M_PER_MI = 1609.344
FT_PER_M = 3.28084
RUN_TYPES = ("running", "trail_running", "treadmill_running", "track_running")
HIKE_TYPES = ("hiking", "mountaineering", "walking")

TILES = [  # metric, label, unit, decimals, whether higher is better (for the delta's wording only)
    ("sleep_h", "Sleep", "h", 1, True),
    ("hrv_night_ms", "HRV", "ms", 0, True),
    ("rhr", "Resting HR", "bpm", 0, False),
    ("bb_wake", "Body Battery at wake", "", 0, True),
    ("readiness", "Readiness (Garmin)", "", 0, True),
    ("vo2max", "VO2 max", "", 1, True),
]


def _source(conn) -> str:
    has_real = conn.execute("SELECT 1 FROM metrics WHERE source = 'garmin' LIMIT 1").fetchone()
    return "garmin" if has_real else "sample"


def body(days: int = 30) -> dict:
    days = 90 if days == 90 else 30
    with db.session() as conn:
        src = _source(conn)
        if src == "sample":  # the sample is a fixed window; anchor on its last day
            last = conn.execute("SELECT MAX(day) FROM metrics WHERE source = 'sample'").fetchone()[0]
            if not last:
                return {"empty": True}
            anchor = date.fromisoformat(last)
        else:
            anchor = date.today()
        start = anchor - timedelta(days=days - 1)

        def series(metric: str, since: date = start) -> list[tuple[str, float]]:
            return conn.execute(
                "SELECT day, value FROM metrics WHERE metric = ? AND source = ? AND day BETWEEN ? AND ? ORDER BY day",
                (metric, src, since.isoformat(), anchor.isoformat())).fetchall()

        by_day: dict[str, dict] = {}
        for m in ("sleep_h", "sleep_score", "sleep_deep_h", "sleep_rem_h", "bed_time", "wake_time",
                  "hrv_night_ms", "hrv_week_ms", "rhr"):
            for d, v in series(m):
                by_day.setdefault(d, {"day": d})[m] = v
        daily = [by_day[d] for d in sorted(by_day)]

        tiles = []
        for metric, label, unit, dec, up_good in TILES:
            pts = series(metric, anchor - timedelta(days=89 if metric == "vo2max" else days - 1))
            if not pts:
                continue
            day, value = pts[-1]
            window = [v for d, v in pts if d >= start.isoformat()]
            avg = sum(window) / len(window) if window else None
            tiles.append({"metric": metric, "label": label, "unit": unit, "dec": dec, "up_good": up_good,
                          "value": value, "day": day, "avg": avg, "n": len(window),
                          "spark": [v for _, v in pts[-14:]]})

        n_weeks = 8 if days == 30 else 13
        week0 = anchor - timedelta(days=anchor.weekday()) - timedelta(weeks=n_weeks - 1)
        acts = conn.execute(
            """SELECT start, type, name, distance_m, duration_s, elev_gain_m, avg_hr FROM activities
               WHERE source = ? AND start >= ? ORDER BY start DESC""",
            (src, min(week0, start).isoformat())).fetchall()

    weeks = []
    for i in range(n_weeks):
        ws = week0 + timedelta(weeks=i)
        we = (ws + timedelta(days=7)).isoformat()
        wk = [a for a in acts if ws.isoformat() <= a[0][:10] < we]
        weeks.append({
            "week": ws.isoformat(),
            "run_mi": round(sum(a[3] or 0 for a in wk if a[1] in RUN_TYPES) / M_PER_MI, 1),
            "hike_mi": round(sum(a[3] or 0 for a in wk if a[1] in HIKE_TYPES) / M_PER_MI, 1),
            "runs": sum(1 for a in wk if a[1] in RUN_TYPES),
            "hikes": sum(1 for a in wk if a[1] in HIKE_TYPES),
        })

    recent = []
    for s, typ, name, dist, dur, elev, hr in acts:
        if s[:10] < start.isoformat() or len(recent) >= 12:
            break
        mi = (dist or 0) / M_PER_MI
        recent.append({"start": s, "type": typ, "name": name, "mi": round(mi, 2) if mi else None,
                       "dur_s": dur, "pace_s": round(dur / mi) if mi > 0.3 and dur and typ in RUN_TYPES else None,
                       "elev_ft": round(elev * FT_PER_M) if elev else None, "avg_hr": hr})

    return {"source": src, "days": days, "start": start.isoformat(), "end": anchor.isoformat(),
            "tiles": tiles, "daily": daily, "weeks": weeks, "activities": recent}
