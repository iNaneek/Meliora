"""Body overview: the left column of the Body view.

Python decides everything here: how each number compares to your usual range, and which
stats stand out. Every line carries its number and date (receipts). The local model only
writes the one-sentence headline from those lines. Its sentence is thrown out if it uses
a number that isn't in the facts, or gives advice (on-device never makes training calls).
In that case, or when Ollama is off, a plain Python sentence is shown instead.

The overview always describes "now". It doesn't follow the 30/90-day toggle.
"""

import hashlib
import json
import logging
import re
import statistics
import threading
from datetime import date, timedelta

from meliora import body, db, llm

log = logging.getLogger(__name__)

BASE_DAYS = 30      # "usual" = the 30 days before the latest value
MIN_BASE = 7        # fewer points than this and there's no usual range to compare to
FRESH_DAYS = 2      # a daily metric's record only counts if it's from the last 2 days
ACT_DAYS = 10       # an activity record only counts if it's from the last 10 days
MIN_GAP = 21        # "highest since X" needs X to be at least 3 weeks back
MAX_STANDOUTS = 4

# metric, label, unit, higher is better, minimum half-width of the usual band
ROWS = [
    ("hrv_night_ms", "HRV", "ms", True, 3),
    ("rhr", "Resting HR", "bpm", False, 1),
    ("bb_wake", "Body Battery at wake", "", True, 5),
]
# Daily metrics checked for "highest/lowest since": metric, name, unit, higher is better
RECORD_METRICS = [
    ("hrv_night_ms", "HRV", "ms", True),
    ("rhr", "resting HR", "bpm", False),
    ("sleep_h", "sleep", "", True),
    ("sleep_score", "sleep score", "", True),
    ("bb_wake", "Body Battery at wake", "", True),
]


# ---------- formatting ----------

def _d(day: str | date) -> str:
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return f"{d:%b} {d.day}"


def _hm(h: float) -> str:
    m = round(h * 60)
    return f"{m // 60}h {m % 60:02d}m"


def _val(metric: str, v: float, unit: str = "") -> str:
    if metric.startswith("sleep_h"):
        return _hm(v)
    s = f"{v:.1f}" if metric == "vo2max" else f"{round(v)}"
    return f"{s} {unit}".strip()


# ---------- state rows ----------

def _series(conn, src: str, metric: str, until: date) -> list[tuple[str, float]]:
    return conn.execute(
        "SELECT day, value FROM metrics WHERE metric = ? AND source = ? AND day <= ? ORDER BY day",
        (metric, src, until.isoformat())).fetchall()


def _stale(day: str, anchor: date) -> str | None:
    return None if day == anchor.isoformat() else _d(day)


def _metric_row(pts, anchor, metric, label, unit, up_good, floor) -> dict | None:
    if not pts:
        return None
    day, v = pts[-1]
    since = (date.fromisoformat(day) - timedelta(days=BASE_DAYS)).isoformat()
    base = [x for d, x in pts if since <= d < day]
    row = {"key": metric, "label": label, "value": _val(metric, v, unit), "as_of": _stale(day, anchor)}
    if len(base) < MIN_BASE:
        return {**row, "word": "Not enough history", "tone": "usual", "receipt": "", "short": row["value"]}
    mu, sd = statistics.mean(base), max(statistics.pstdev(base), floor)
    lo, hi = round(mu - sd), round(mu + sd)
    pos = "below" if round(v) < lo else "above" if round(v) > hi else "usual"
    tone = "usual" if pos == "usual" else ("good" if (pos == "above") == up_good else "watch")
    word = {"usual": "Usual", "above": "Above usual", "below": "Below usual"}[pos]
    return {**row, "word": word, "tone": tone, "receipt": f"usual {lo}–{hi}{(' ' + unit) if unit else ''}",
            "short": row["value"]}


def _sleep_row(pts, anchor) -> dict | None:
    if not pts:
        return None
    day, last = pts[-1]
    end = date.fromisoformat(day)
    week = [v for d, v in pts if d > (end - timedelta(days=7)).isoformat()]
    base = [v for d, v in pts if (end - timedelta(days=7 + BASE_DAYS)).isoformat() < d <= (end - timedelta(days=7)).isoformat()]
    row = {"key": "sleep_h", "label": "Sleep", "value": _hm(last), "as_of": _stale(day, anchor)}
    avg = statistics.mean(week)
    if len(base) < MIN_BASE:
        return {**row, "word": "Not enough history", "tone": "usual",
                "receipt": f"{len(week)}-night avg {_hm(avg)}", "short": _hm(avg)}
    mu = statistics.mean(base)
    receipt = f"{len(week)}-night avg {_hm(avg)} vs usual {_hm(mu)}"
    # One night far off (an hour or more) is the story; otherwise the week's average is.
    if day == anchor.isoformat() and abs(last - mu) >= 1:
        short = last < mu
        return {**row, "word": "Short night" if short else "Long night", "tone": "watch" if short else "good",
                "receipt": receipt, "short": f"{_hm(last)} last night"}
    diff = avg - mu
    word, tone = ("More than usual", "good") if diff >= 0.5 else ("Less than usual", "watch") if diff <= -0.5 else ("Usual", "usual")
    return {**row, "word": word, "tone": tone, "receipt": receipt, "short": f"{len(week)}-night avg {_hm(avg)}"}


def _load_row(acts, anchor) -> dict | None:
    """Last 7 days of activity vs the 4 weeks before."""
    a7 = (anchor - timedelta(days=6)).isoformat()
    a35 = (anchor - timedelta(days=34)).isoformat()
    week = [a for a in acts if a["day"] >= a7]
    prior = [a for a in acts if a35 <= a["day"] < a7]
    if not week and not prior:
        return None
    mi = sum(a["mi"] for a in week if a["kind"] in ("run", "hike"))
    base_mi = sum(a["mi"] for a in prior if a["kind"] in ("run", "hike")) / 4
    base_n = len(prior) / 4
    n = len(week)
    value = f"{n} {'activity' if n == 1 else 'activities'}" + (f", {mi:.1f} mi" if mi else "")
    # Judge by miles when there's a running/hiking habit, otherwise by how many sessions.
    if base_mi >= 5:
        ratio, receipt = mi / base_mi, f"usual {base_mi:.1f} mi/week"
    elif base_n:
        ratio, receipt = n / base_n, f"usual {base_n:.1f}/week"
    else:
        ratio, receipt = None, ""
    if ratio is None:
        word, tone = "Not enough history", "usual"
    elif ratio >= 1.25:
        word, tone = "More than usual", "good"
    elif ratio <= 0.75:
        word, tone = "Less than usual", "watch"
    else:
        word, tone = "Usual", "usual"
    return {"key": "load", "label": "Training, last 7 days", "value": value, "as_of": None,
            "word": word, "tone": tone, "receipt": receipt, "short": value}


# ---------- stand-outs ----------

def _record(pts, i: int, higher: bool) -> tuple[str | None, int] | None:
    """For point i: (day of the last point that matched or beat it, days back). None if it's no record.
    If nothing earlier beats it, the first day of data stands in, marked with None."""
    day, v = pts[i]
    for d, x in reversed(pts[:i]):
        if (x >= v) if higher else (x <= v):
            gap = (date.fromisoformat(day) - date.fromisoformat(d)).days
            return (d, gap) if gap >= MIN_GAP else None
    if i < 10:  # too little history before it to call it a record
        return None
    return None, (date.fromisoformat(day) - date.fromisoformat(pts[0][0])).days


def _phrase(top: str, name: str, rec: tuple[str | None, int]) -> str:
    since, gap = rec
    return f"{top} {name} since {_d(since)}" if since else f"{top} {name} in {gap} days of data"


def _metric_standouts(conn, src, anchor) -> list[dict]:
    out = []
    fresh = (anchor - timedelta(days=FRESH_DAYS - 1)).isoformat()
    for metric, name, unit, up_good in RECORD_METRICS:
        pts = _series(conn, src, metric, anchor)
        if not pts or pts[-1][0] < fresh:
            continue
        i = len(pts) - 1
        for higher in (True, False):
            rec = _record(pts, i, higher)
            if rec:
                top = ("Most" if higher else "Least") if metric == "sleep_h" else ("Highest" if higher else "Lowest")
                out.append({"key": metric, "title": _phrase(top, name, rec), "value": _val(metric, pts[i][1], unit),
                            "day": _d(pts[i][0]), "tone": "good" if higher == up_good else "watch", "score": rec[1]})
    # VO2 max moves slowly and only after qualifying runs: compare with a month ago.
    vo2 = _series(conn, src, "vo2max", anchor)
    if vo2 and vo2[-1][0] >= (anchor - timedelta(days=ACT_DAYS)).isoformat():
        day, v = vo2[-1]
        old = [(d, x) for d, x in vo2 if d <= (date.fromisoformat(day) - timedelta(days=28)).isoformat()]
        if old and abs(v - old[-1][1]) >= 0.5:
            up = v > old[-1][1]
            out.append({"key": "vo2max", "title": f"VO2 max {'up' if up else 'down'} since {_d(old[-1][0])}",
                        "value": f"{v:.1f} (was {old[-1][1]:.1f})", "day": _d(day),
                        "tone": "good" if up else "watch", "score": 40})
    return out


def _activities(conn, src, anchor) -> list[dict]:
    rows = conn.execute(
        "SELECT start, type, name, distance_m, duration_s, elev_gain_m FROM activities"
        " WHERE source = ? AND start < ? ORDER BY start",
        (src, (anchor + timedelta(days=1)).isoformat())).fetchall()
    out = []
    for start, typ, name, dist, dur, elev in rows:
        mi = (dist or 0) / body.M_PER_MI
        kind = "run" if typ in body.RUN_TYPES else "hike" if typ in body.HIKE_TYPES else "other"
        out.append({"day": start[:10], "kind": kind, "name": name, "mi": mi, "dur": dur or 0,
                    "pace": dur / mi if kind == "run" and mi >= 3 and dur else None,
                    "ft": (elev or 0) * body.FT_PER_M})
    return out


def _activity_standouts(acts, anchor) -> list[dict]:
    recent_from = (anchor - timedelta(days=ACT_DAYS - 1)).isoformat()
    checks = [  # key, which activities, measure, higher wins, phrase, value text
        ("run_mi", "run", "mi", True, ("Longest", "run"), lambda a: f"{a['mi']:.1f} mi"),
        ("run_pace", "run", "pace", False, ("Fastest", "run of 3+ mi"),
         lambda a: f"{int(a['pace'] // 60)}:{int(a['pace'] % 60):02d} /mi"),
        ("elev", None, "ft", True, ("Most climbing", "in one activity"), lambda a: f"{round(a['ft']):,} ft"),
    ]
    out = []
    for key, kind, field, higher, (top, name), show in checks:
        pts = [a for a in acts if (kind is None or a["kind"] == kind) and a[field]]
        if key == "elev":
            pts = [a for a in pts if a["ft"] >= 500]
        series = [(a["day"], a[field]) for a in pts]
        best = None
        for i, a in enumerate(pts):
            if a["day"] < recent_from:
                continue
            rec = _record(series, i, higher)
            if rec and (not best or rec[1] > best[1][1]):
                best = (a, rec)
        if best:
            a, rec = best
            title = (f"{top} {name} since {_d(rec[0])}" if rec[0] else f"{top} {name} in {rec[1]} days of data")
            out.append({"key": key, "title": title, "value": show(a), "day": _d(a["day"]),
                        "detail": a["name"], "tone": "good", "score": rec[1]})
    return out


# ---------- the overview ----------

def facts() -> dict | None:
    with db.session() as conn:
        found = body.find_anchor(conn)
        if not found:
            return None
        src, anchor = found
        rows = [_metric_row(_series(conn, src, m, anchor), anchor, m, label, unit, up, floor)
                for m, label, unit, up, floor in ROWS]
        rows.insert(2, _sleep_row(_series(conn, src, "sleep_h", anchor), anchor))
        acts = _activities(conn, src, anchor)
        rows.append(_load_row(acts, anchor))
        stand = _metric_standouts(conn, src, anchor) + _activity_standouts(acts, anchor)
    stand.sort(key=lambda s: -s["score"])
    seen, picked = set(), []
    for s in stand:  # at most one stand-out per metric
        if s["key"] not in seen:
            seen.add(s["key"])
            picked.append(s)
    return {"source": src, "as_of": _d(anchor), "rows": [r for r in rows if r],
            "standouts": picked[:MAX_STANDOUTS]}


def _fact_lines(f: dict) -> list[str]:
    lines = []
    for r in sorted(f["rows"], key=lambda r: r["tone"] == "usual"):  # unusual first
        line = f"{r['label']}: {r['value']} ({r['word'].lower()}"
        line += f"; {r['receipt']})" if r["receipt"] else ")"
        if r["as_of"]:
            line += f", as of {r['as_of']}"
        lines.append(line)
    for s in f["standouts"]:
        when = "today" if s["day"] == f["as_of"] else f"on {s['day']}"
        lines.append(f"{s['title']}: {s['value']} {when}")
    return lines


def _plain_headline(f: dict) -> str:
    """The no-model sentence: what's outside the usual range, plus the top stand-out."""
    off = [r for r in f["rows"] if r["tone"] != "usual"]
    if not off:
        names = [r["label"].split(",")[0].lower().replace("hrv", "HRV") for r in f["rows"]]
        listed = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
        lead = f"Your {listed} are all in their usual range."
    else:
        notes = []
        for r in off[:2]:
            if r["word"].endswith("night"):
                notes.append(f"{r['word'].lower()} ({r['short']})")
            else:
                name = r["label"].split(",")[0].lower().replace("hrv", "HRV").replace("body battery", "Body Battery")
                notes.append(f"{name} {r['word'].lower()} ({r['short']})")
        lead = " and ".join(notes) + "."
        lead = lead[0].upper() + lead[1:]
    if f["standouts"]:
        s = f["standouts"][0]
        lead += f" {s['title']}: {s['value']}."
    return lead


SYSTEM = """You write the one-sentence headline at the top of a personal body-data dashboard.
Rules:
- One sentence, at most 25 words, addressed to the reader as "your".
- Pick the one or two most notable facts. Do not list everything.
- Use only the facts given. Copy any number exactly as written, with its unit.
- Describe only. Never advise or suggest anything (no training, resting, sleeping, recovering, pushing).
- Calm and plain. No exclamation marks. No praise words like great, amazing, impressive.
- Lead with what is out of the usual range. Skip anything marked usual unless everything is.

Example facts:
- HRV: 41 ms (above usual; usual 30-38 ms)
- Sleep: 8h 10m (usual; 7-night avg 7h 30m vs usual 7h 25m)
- Longest run since Aug 2: 9.4 mi on Oct 3
Example headline: Your HRV is above its usual range at 41 ms, and Oct 3 was your longest run since Aug 2."""

_BANNED = re.compile(r"\b(should|recommend\w*|consider|try|avoid|take it easy|go easy|rest day|need to|make sure|"
                     r"great|amazing|impressive|awesome|excellent)\b|!", re.I)
_NUM = re.compile(r"\d+(?:[.:,]\d+)*")


def _valid(text: str, lines: list[str]) -> bool:
    if not text or len(text) > 220 or _BANNED.search(text):
        return False
    allowed = set(_NUM.findall("\n".join(lines)))
    return all(n in allowed for n in _NUM.findall(text))


def _fingerprint(lines: list[str], model: str) -> str:
    return hashlib.sha1(json.dumps([model, SYSTEM, lines]).encode()).hexdigest()


def _cached(fp: str) -> dict | None:
    with db.session() as conn:
        row = conn.execute("SELECT text, model FROM summaries WHERE key = 'body' AND fingerprint = ?", (fp,)).fetchone()
    return {"text": row[0], "by": row[1]} if row else None


def overview() -> dict:
    """Fast: facts plus a headline. The headline is the cached model sentence when the facts
    haven't changed, otherwise the plain one with `pending` set so the UI asks for a fresh one."""
    f = facts()
    if not f:
        return {"empty": True}
    lines = _fact_lines(f)
    hit = _cached(_fingerprint(lines, llm.settings()["fast"]))
    f["headline"] = ({**hit, "pending": False} if hit else
                     {"text": _plain_headline(f), "by": "plain", "pending": True})
    return f


_gen_lock = threading.Lock()


def headline() -> dict:
    """Write (or reuse) the model headline for the current facts. Only runs when Body is open
    (battery). About 2 s with the model loaded, ~8-10 s when Ollama has to start first."""
    with _gen_lock:  # app launch and the UI can ask at once; the second one hits the cache
        f = facts()
        if not f:
            return {"text": "", "by": "plain", "pending": False}
        lines = _fact_lines(f)
        model = llm.settings()["fast"]
        fp = _fingerprint(lines, model)
        hit = _cached(fp)
        if hit:
            return {**hit, "pending": False}
        plain = {"text": _plain_headline(f), "by": "plain", "pending": False}
        user = "Facts (state first, then stand-outs):\n" + "\n".join(f"- {line}" for line in lines)
        schema = {"type": "object", "properties": {"headline": {"type": "string"}}, "required": ["headline"]}
        for _ in range(2):  # one retry if the first sentence fails the check
            try:
                text = str(llm.local_json("body_headline", SYSTEM, user, schema).get("headline", "")).strip()
            except llm.Unavailable:
                return {**plain, "offline": True}
            if text:
                text = text[0].upper() + text[1:]
                text = text if text.endswith((".", "?")) else text + "."
            if _valid(text, lines):
                with db.session() as conn:
                    conn.execute("INSERT OR REPLACE INTO summaries (key, fingerprint, text, model, created_at)"
                                 " VALUES ('body', ?, ?, ?, ?)", (fp, text, model, db.now()))
                return {"text": text, "by": model, "pending": False}
            log.info("body headline rejected: %r", text)
        return plain


if __name__ == "__main__":
    print(json.dumps(facts(), indent=2))
    print(_fact_lines(facts()))
    print(headline())
