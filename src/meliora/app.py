"""The Meliora window: pywebview (WKWebView) with a Python js_api."""

import logging
import os
import threading
from datetime import date, datetime
from pathlib import Path

import webview

from meliora import config, db, rules, weather

UI = Path(__file__).parent / "ui" / "index.html"


class Api:
    """Every public method here is callable from JS as `pywebview.api.<name>()`."""

    def today(self) -> dict:
        now = datetime.now()
        return rules.decide(rules.demo_day(), db.decisions(now.date().isoformat()), now)

    def decide(self, block_id: str, decision: str) -> dict:
        if decision not in ("confirm", "decline"):
            raise ValueError(decision)
        # Pencil before ink: this only records the choice. Nothing is written to Calendar yet.
        db.record_decision(date.today().isoformat(), block_id, decision)
        return self.today()

    def undo(self, block_id: str) -> dict:
        db.clear_decision(date.today().isoformat(), block_id)
        return self.today()

    def reset(self) -> dict:
        db.clear_decisions(date.today().isoformat())
        return self.today()

    def sources(self) -> dict:
        return {"weather": weather.last_synced(), "weather_busy": _weather_busy.is_set(),
                "today": weather.today_line()}

    def home(self) -> dict:
        h = config.home()
        return {"name": h["name"], "lat": h["lat"], "lon": h["lon"]}

    def ask(self, text: str) -> str:
        state = self.today()
        nxt = state["next"]
        where = f"{nxt['what']} ({nxt['label'].lower()})" if nxt else "nothing else today"
        return (
            "Chat isn't wired to Qwen3 or Claude yet (Phase 0, step 7). "
            f"Your next thing is {where}."
        )


def _set_app_name(name: str) -> None:
    """Show 'Meliora' instead of 'Python' in the menu bar."""
    try:
        from Foundation import NSBundle

        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = name
    except Exception:
        pass


_weather_busy = threading.Event()


def _refresh_weather() -> None:
    """Runs off the UI thread; on failure the cached copy stays and the sidebar says when it's from."""
    if not weather.is_stale():
        return
    _weather_busy.set()
    try:
        logging.info("weather refresh: %s", weather.refresh())
    except Exception:
        logging.exception("weather refresh failed")
    finally:
        _weather_busy.clear()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    threading.Thread(target=_refresh_weather, daemon=True).start()
    _set_app_name("Meliora")
    webview.create_window(
        "Meliora",
        url=UI.as_uri(),
        js_api=Api(),
        width=1360,
        height=880,
        min_size=(1100, 720),
    )
    # MELIORA_DEBUG=1 enables right-click → Inspect Element for live CSS tweaking.
    webview.start(debug=bool(os.environ.get("MELIORA_DEBUG")))
