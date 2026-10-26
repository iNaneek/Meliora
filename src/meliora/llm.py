"""Model router. Every call is logged to `llm_calls` with its time and token counts.

Local first: Ollama (Qwen3) runs on the Mac, free and offline. Callers always have a
plain-Python fallback, because the model may be off, slow, or say something unusable.
Claude (`claude -p`) gets added here when a feature needs it.
"""

import atexit
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

from meliora import config, db

log = logging.getLogger(__name__)
DEFAULTS = {"fast": "qwen3:4b", "ollama_url": "http://localhost:11434",
            "ollama_bin": "/Applications/Ollama.app/Contents/Resources/ollama"}
KEEP_ALIVE = "5m"  # the model leaves memory (~3 GB) 5 min after its last use
PID_FILE = config.DATA_DIR / "ollama.pid"
# Context window in tokens. Ollama otherwise sizes it to the Mac's memory (262k here), which
# reserved 43 GB for a 3 GB model. Prompts here are ~500 tokens.
NUM_CTX = 4096


class Unavailable(Exception):
    """The model couldn't answer (Ollama not running, model missing, timeout, bad JSON)."""


def settings() -> dict:
    return {**DEFAULTS, **config.load().get("models", {})}


# ---------- the Ollama server: started on first use, stopped when Meliora quits ----------
# Battery: the Ollama app (menu-bar icon, updater) is never opened. Meliora runs only the
# bare `ollama serve`, and only once something actually needs the model.

_server_lock = threading.Lock()
_owned_pid: int | None = None  # set when Meliora started the server, so it's ours to stop


def _up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/version", timeout=1):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ensure_server() -> None:
    """Start `ollama serve` if nothing is listening. Raises Unavailable if it can't."""
    global _owned_pid
    s = settings()
    with _server_lock:
        if _up(s["ollama_url"]):
            if _owned_pid is None and PID_FILE.exists():  # left running by a Meliora that crashed: adopt it
                pid = int(PID_FILE.read_text() or 0)
                _owned_pid = pid if pid and _pid_alive(pid) else None
            return
        exe = s["ollama_bin"] if os.path.exists(s["ollama_bin"]) else shutil.which("ollama")
        if not exe:
            raise Unavailable("Ollama isn't installed")
        logf = open(config.DATA_DIR / "ollama.log", "ab")
        proc = subprocess.Popen([exe, "serve"], stdout=logf, stderr=logf, stdin=subprocess.DEVNULL)
        _owned_pid = proc.pid
        PID_FILE.write_text(str(proc.pid))
        log.info("started ollama serve (pid %d)", proc.pid)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if _up(s["ollama_url"]):
                return
            if proc.poll() is not None:
                break
            time.sleep(0.25)
        raise Unavailable("ollama serve didn't come up")


def shutdown() -> None:
    """Stop the server if Meliora started it. An Ollama someone else started is left alone."""
    global _owned_pid
    pid, _owned_pid = _owned_pid, None
    if pid and _pid_alive(pid):
        try:
            os.kill(pid, 15)  # SIGTERM: ollama unloads models and exits
            log.info("stopped ollama serve (pid %d)", pid)
        except OSError:
            pass
    PID_FILE.unlink(missing_ok=True)


atexit.register(shutdown)


def _log(model: str, task: str, ms: int, tin, tout, ok: bool, detail: str = "") -> None:
    try:
        with db.session() as conn:
            conn.execute(
                "INSERT INTO llm_calls (at, backend, model, task, ms, tokens_in, tokens_out, ok, detail)"
                " VALUES (?, 'ollama', ?, ?, ?, ?, ?, ?, ?)",
                (db.now(), model, task, ms, tin, tout, int(ok), detail[:200]))
    except Exception:
        log.exception("couldn't log model call")


def local_json(task: str, system: str, user: str, schema: dict, tier: str = "fast",
               timeout: float = 30) -> dict:
    """Ask the local model for JSON matching `schema`. Raises Unavailable on any failure."""
    s = settings()
    model = s[tier]
    t0 = time.monotonic()
    try:
        ensure_server()
    except Unavailable as e:
        _log(model, task, int((time.monotonic() - t0) * 1000), None, None, False, str(e))
        raise
    body = {
        "model": model, "stream": False, "think": False, "keep_alive": KEEP_ALIVE,
        "format": schema, "options": {"temperature": 0.3, "num_ctx": NUM_CTX},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    req = urllib.request.Request(s["ollama_url"].rstrip("/") + "/api/chat",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
        out = json.loads(resp["message"]["content"])
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as e:
        _log(model, task, int((time.monotonic() - t0) * 1000), None, None, False, repr(e))
        raise Unavailable(str(e)) from e
    _log(model, task, int((time.monotonic() - t0) * 1000),
         resp.get("prompt_eval_count"), resp.get("eval_count"), True)
    return out
