"""The Meliora window: pywebview (WKWebView) with a Python js_api."""

import logging
import os
import threading
from datetime import date, datetime
from pathlib import Path

import webview

from meliora import body, calendars, chat, config, db, garmin, llm, overview, proposals, rules, weather

UI = Path(__file__).parent / "ui" / "index.html"


class Api:
    """Every public method here is callable from JS as `pywebview.api.<name>()`."""

    def today(self) -> dict:
        now = datetime.now()
        return rules.decide(rules.today_day(now), db.decisions(now.date().isoformat()), now)

    def decide(self, block_id: str, decision: str) -> dict:
        if decision not in ("confirm", "decline"):
            raise ValueError(decision)
        if block_id.startswith("prop-"):  # an event proposed in Ask: Confirm writes it to Calendar
            r = self.proposal(int(block_id[5:]), "add" if decision == "confirm" else "skip")
            return {**self.today(), "msg": r["msg"]}
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
                "today": weather.today_line(), "garmin": garmin.status(),
                "calendar": calendars.sync_status()}

    def calendar_connect(self) -> dict:
        """The sidebar's Connect button: macOS asks once, then events are read in."""
        access = calendars.request_access()
        if access == "granted":
            n = calendars.refresh(force=True)
            return {"ok": True, "msg": f"Calendar connected: {n} events in the next 3 weeks."}
        if access in ("denied", "restricted", "write_only"):
            return {"ok": False, "msg": "Calendar access is off. Turn on Meliora in System Settings → "
                    "Privacy & Security → Calendars, then relaunch."}
        return {"ok": False, "msg": "No answer from macOS. Try Connect again."}

    def garmin_sync(self) -> dict:
        """The Sync button. pywebview runs js_api calls off the UI thread, so blocking is fine."""
        try:
            r = garmin.manual_pull()
            return {"ok": True, "msg": ("Garmin synced." if r["sleep_ok"] else
                    "Garmin synced, but last night's sleep isn't there yet. Open Garmin Connect on your phone.")}
        except garmin.NotConnected:
            return {"ok": False, "msg": "Garmin isn't connected. Run `uv run meliora-garmin login` in Terminal."}
        except Exception as e:
            logging.exception("garmin sync failed")
            with db.session() as conn:
                db.mark_sync(conn, garmin.SOURCE, False, str(e)[:200])
            return {"ok": False, "msg": "Garmin sync failed. Using the last good copy."}

    def body(self, days: int = 30) -> dict:
        return body.body(int(days))

    def body_overview(self) -> dict:
        """Instant: the facts, plus the cached headline (or the plain one, marked pending)."""
        return overview.overview()

    def body_headline(self) -> dict:
        """Slow (model call). The UI asks for this only when the overview says pending."""
        return overview.headline()

    def home(self) -> dict:
        h = config.home()
        return {"name": h["name"], "lat": h["lat"], "lon": h["lon"]}

    def ask(self, text: str, tier: str = "fast", history: list | None = None) -> dict:
        """The Ask drawer. Slow (a model call); pywebview runs this off the UI thread."""
        if tier in dict(llm.CLAUDE_TIERS):
            return chat.answer_claude(str(text)[:4000], history or [], tier)
        if tier not in dict((t, 1) for t, _, _ in llm.TIERS):
            tier = "fast"
        return chat.answer(str(text)[:2000], history or [], tier)

    def chat_models(self) -> list:
        return llm.tiers() + llm.claude_tiers()

    def proposal(self, pid: int, action: str) -> dict:
        """Confirm ("add") writes the event to the Meliora calendar; "skip" drops it."""
        pid = int(pid)
        if action == "skip":
            return {"ok": True, "proposal": proposals.skip(pid), "msg": "Skipped. Nothing was added."}
        try:
            p = proposals.confirm(pid)
        except PermissionError:
            return {"ok": False, "proposal": proposals.get(pid),
                    "msg": "Connect Calendar first (sidebar), then confirm again."}
        except Exception as e:
            logging.exception("adding proposal %s failed", pid)
            return {"ok": False, "proposal": proposals.get(pid), "msg": f"Calendar didn't take it: {e}"[:200]}
        return {"ok": True, "proposal": p, "msg": f"Added to your Meliora calendar: {p['title']}."}

    def chat_warm(self, tier: str = "fast") -> None:
        """Drawer opened: load the model in the background so the first answer is quicker."""
        if tier in dict(llm.CLAUDE_TIERS):
            return  # nothing to load for Claude
        threading.Thread(target=llm.warm, args=(tier,), daemon=True).start()


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


def _garmin_auto(reason: str) -> None:
    threading.Thread(target=garmin.auto_pull, args=(reason,), daemon=True).start()


_wake_observer = None  # kept alive for the life of the app


def _watch_wake() -> None:
    """Run the Garmin auto pull when the Mac wakes. macOS tells us; nothing polls."""
    global _wake_observer
    try:
        from AppKit import NSWorkspace, NSWorkspaceDidWakeNotification
        from Foundation import NSOperationQueue

        center = NSWorkspace.sharedWorkspace().notificationCenter()
        _wake_observer = center.addObserverForName_object_queue_usingBlock_(
            NSWorkspaceDidWakeNotification, None, NSOperationQueue.mainQueue(),
            lambda _note: _garmin_auto("wake"))
    except Exception:
        logging.exception("couldn't watch for wake")


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    threading.Thread(target=_refresh_weather, daemon=True).start()
    _garmin_auto("launch")
    _watch_wake()
    _set_app_name("Meliora")
    window = webview.create_window(
        "Meliora",
        url=UI.as_uri(),
        js_api=Api(),
        width=1360,
        height=880,
        min_size=(1100, 720),
    )
    window.events.closed += llm.shutdown  # stop the Ollama server if Meliora started it
    # MELIORA_DEBUG=1 enables right-click → Inspect Element for live CSS tweaking.
    webview.start(debug=bool(os.environ.get("MELIORA_DEBUG")))
