"""Weather collector: Open-Meteo models for every place in config.toml, plus NWS.

Writes to SQLite and keeps the last good copy, so everything still works offline.
Run by hand with `uv run meliora-weather` (fetch + print a quick snow summary).
"""

import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from meliora import config, db

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
NWS = "https://api.weather.gov"
TZ = "America/Denver"

# Open-Meteo variable → weather_hourly column. Kept at 10 so each request costs one call.
HOURLY = {
    "temperature_2m": "temp_c",
    "apparent_temperature": "feels_c",
    "precipitation": "precip_mm",
    "snowfall": "snow_cm",
    "snow_depth": "snow_depth_m",
    "freezing_level_height": "freezing_m",
    "weather_code": "code",
    "cloud_cover": "cloud_pct",
    "wind_gusts_10m": "gust_kmh",
    "cape": "cape",
}


def _get(url: str, params: dict | None = None, headers: dict | None = None, tries: int = 3) -> dict | list:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers or {})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:  # rate limited: wait it out
                time.sleep(65)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(3)
                continue
            raise


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _mark(conn: sqlite3.Connection, source: str, ok: bool, detail: str = "") -> None:
    conn.execute(
        """INSERT INTO source_sync (source, last_ok, last_try, detail) VALUES (?, ?, ?, ?)
           ON CONFLICT(source) DO UPDATE SET
             last_ok = COALESCE(excluded.last_ok, last_ok), last_try = excluded.last_try, detail = excluded.detail""",
        (source, _now() if ok else None, _now(), detail),
    )


def save_places(conn: sqlite3.Connection, places: list[dict]) -> None:
    conn.execute("DELETE FROM places")
    conn.executemany(
        "INSERT INTO places (id, name, kind, range, lat, lon, elev_m) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(p["id"], p["name"], p["kind"], p.get("range"), p["lat"], p["lon"], p["elev_m"]) for p in places],
    )


def fetch_model(places: list[dict], model: str, days: int) -> list[tuple]:
    """One request per model covers every place (Open-Meteo takes coordinate lists)."""
    data = _get(OPEN_METEO, {
        "latitude": ",".join(str(p["lat"]) for p in places),
        "longitude": ",".join(str(p["lon"]) for p in places),
        "elevation": ",".join(str(p["elev_m"]) for p in places),
        "hourly": ",".join(HOURLY),
        "models": model,
        "forecast_days": days,
        "timezone": TZ,
    })
    if isinstance(data, dict):  # a single place comes back as an object, not a list
        data = [data]
    rows = []
    for place, d in zip(places, data):
        h = d["hourly"]
        cols = [h.get(v, [None] * len(h["time"])) for v in HOURLY]
        for i, t in enumerate(h["time"]):
            vals = [c[i] for c in cols]
            if any(v is not None for v in vals):  # short-range models pad the tail with nulls
                rows.append((place["id"], model, t, *vals))
    return rows


def fetch_open_meteo(conn: sqlite3.Connection, places: list[dict], models: list[str], days: int) -> dict:
    report = {}
    cols = ", ".join(HOURLY.values())
    marks = ", ".join("?" * (len(HOURLY) + 3))
    for model in models:
        try:
            rows = fetch_model(places, model, days)
        except Exception as e:  # keep the old rows for this model; say so in source_sync
            _mark(conn, f"open-meteo:{model}", False, str(e)[:200])
            report[model] = f"failed ({e})"
            continue
        with conn:
            conn.execute("DELETE FROM weather_hourly WHERE model = ?", (model,))
            conn.executemany(f"INSERT INTO weather_hourly (place_id, model, time, {cols}) VALUES ({marks})", rows)
            _mark(conn, f"open-meteo:{model}", True, f"{len(rows)} rows")
        report[model] = f"{len(rows)} rows"
    return report


def fetch_nws(conn: sqlite3.Connection, home: dict, user_agent: str) -> dict:
    headers = {"User-Agent": user_agent, "Accept": "application/geo+json"}
    report = {}
    try:
        alerts = _get(f"{NWS}/alerts/active", {"area": "CO"}, headers)["features"]
        with conn:
            conn.execute("DELETE FROM nws_alerts")
            conn.executemany(
                "INSERT OR REPLACE INTO nws_alerts VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(a["properties"]["id"], a["properties"]["event"], a["properties"]["severity"],
                  a["properties"]["headline"], a["properties"]["areaDesc"], a["properties"]["onset"],
                  a["properties"].get("ends") or a["properties"].get("expires")) for a in alerts],
            )
            _mark(conn, "nws:alerts", True, f"{len(alerts)} active")
        report["alerts"] = f"{len(alerts)} active in CO"
    except Exception as e:
        _mark(conn, "nws:alerts", False, str(e)[:200])
        report["alerts"] = f"failed ({e})"
    try:
        point = _get(f"{NWS}/points/{home['lat']},{home['lon']}", headers=headers)
        periods = _get(point["properties"]["forecast"], headers=headers)["properties"]["periods"]
        with conn:
            conn.execute("DELETE FROM nws_forecast WHERE place_id = ?", (home["id"],))
            conn.executemany(
                "INSERT INTO nws_forecast VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(home["id"], p["number"], p["name"], p["startTime"], p["endTime"], p["temperature"],
                  p["temperatureUnit"], p["windSpeed"], p["shortForecast"], p["detailedForecast"]) for p in periods],
            )
            _mark(conn, "nws:forecast", True, f"{len(periods)} periods")
        report["forecast"] = f"{len(periods)} periods for {home['name']}"
    except Exception as e:
        _mark(conn, "nws:forecast", False, str(e)[:200])
        report["forecast"] = f"failed ({e})"
    return report


def refresh() -> dict:
    cfg = config.load()
    w, places = cfg["weather"], cfg["places"]
    home = next(p for p in places if p["kind"] == "home")
    conn = db.connect()
    with conn:
        save_places(conn, places)
    report = fetch_open_meteo(conn, places, w["models"], w["forecast_days"])
    report |= fetch_nws(conn, home, w["nws_user_agent"])
    conn.close()
    return report


def is_stale() -> bool:
    hours = config.load()["weather"]["refresh_hours"]
    with db.connect() as conn:
        row = conn.execute("SELECT MAX(last_ok) FROM source_sync WHERE source LIKE 'open-meteo:%'").fetchone()
    return not row[0] or datetime.fromisoformat(row[0]) < datetime.now() - timedelta(hours=hours)


def last_synced() -> str | None:
    with db.connect() as conn:
        return conn.execute("SELECT MAX(last_ok) FROM source_sync WHERE source LIKE 'open-meteo:%'").fetchone()[0]


# ---------- quick look (sanity check, not the real feature yet) ----------

def snow_totals(kind: str, start: datetime, end: datetime) -> list[tuple[str, dict[str, float]]]:
    """Snowfall (cm) per place per model between start and end."""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT p.name, w.model, SUM(w.snow_cm) FROM weather_hourly w JOIN places p ON p.id = w.place_id
               WHERE p.kind = ? AND w.time >= ? AND w.time < ? AND w.snow_cm IS NOT NULL
               GROUP BY p.name, w.model""",
            (kind, start.strftime("%Y-%m-%dT%H:%M"), end.strftime("%Y-%m-%dT%H:%M")),
        ).fetchall()
    out: dict[str, dict[str, float]] = {}
    for name, model, total in rows:
        out.setdefault(name, {})[model] = total
    return sorted(out.items(), key=lambda kv: -max(kv[1].values()))


def _print_snow(title: str, kind: str, start: datetime, end: datetime) -> None:
    print(f"\n{title}")
    for name, by_model in snow_totals(kind, start, end):
        vals = sorted(by_model.values())
        lo, hi = vals[0] / 2.54, vals[-1] / 2.54
        print(f"  {name:<26} {lo:4.1f}–{hi:4.1f} in   ({len(vals)} models)")


def main() -> None:
    print("Fetching weather…")
    for k, v in refresh().items():
        print(f"  {k:<22} {v}")
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    _print_snow("Resort snow, next 72 h (lowest–highest model):", "resort", now, now + timedelta(hours=72))
    sat = date.today() + timedelta(days=(5 - date.today().weekday()) % 7)
    wknd = datetime.combine(sat, datetime.min.time())
    _print_snow(f"14er snow, weekend of {sat:%b %-d}:", "peak", wknd, wknd + timedelta(days=2))


if __name__ == "__main__":
    main()
