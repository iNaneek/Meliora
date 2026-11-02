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
from pathlib import Path

from meliora import config, db

log = logging.getLogger(__name__)
# Instruct (non-thinking) builds: the plain qwen3:4b and qwen3:30b-a3b tags now point at
# thinking-only models that reason for hundreds of tokens before every answer.
DEFAULTS = {"fast": "qwen3:4b-instruct", "medium": "qwen3:8b", "big": "qwen3:30b-instruct",
            "ollama_url": "http://localhost:11434",
            "ollama_bin": "/Applications/Ollama.app/Contents/Resources/ollama"}
# The Ask drawer's model switch: tier, short label, rough download size.
TIERS = [("fast", "4B", "2.5 GB"), ("medium", "8B", "5.2 GB"), ("big", "30B", "18.6 GB")]
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
        for attempt in range(1, GPU_TRIES + 1):
            proc, device = _start(exe, s["ollama_url"])
            if device != "cpu" or attempt == GPU_TRIES:
                break
            # Ollama's GPU probe sometimes fails, and then the whole run is CPU-only (~10x slower,
            # more battery). A fresh start usually finds the GPU again.
            log.warning("ollama started without the GPU (attempt %d); restarting it", attempt)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            time.sleep(1)
        if device == "cpu":
            log.warning("ollama is running on the CPU only; answers will be slow")
        _owned_pid = proc.pid
        PID_FILE.write_text(str(proc.pid))
        log.info("started ollama serve (pid %d, %s)", proc.pid, device)


GPU_TRIES = 3


def _start(exe: str, url: str) -> tuple[subprocess.Popen, str]:
    """Start `ollama serve` and wait until it answers. Returns (process, "gpu"|"cpu"|"unknown"),
    read from the "inference compute" line it writes to its log at startup."""
    log_path = config.DATA_DIR / "ollama.log"
    offset = log_path.stat().st_size if log_path.exists() else 0
    logf = open(log_path, "ab")
    proc = subprocess.Popen([exe, "serve"], stdout=logf, stderr=logf, stdin=subprocess.DEVNULL)
    deadline = time.monotonic() + 20
    device = "unknown"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise Unavailable("ollama serve exited at startup (see data/ollama.log)")
        with open(log_path, "rb") as f:
            f.seek(offset)
            new = f.read().decode(errors="replace")
        line = next((ln for ln in new.splitlines() if '"inference compute"' in ln), None)
        if line:
            device = "cpu" if "library=cpu" in line else "gpu"
        if line and _up(url):
            return proc, device
        time.sleep(0.25)
    proc.terminate()
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


def installed(model: str) -> bool:
    """Is the model downloaded? Read from disk, so asking doesn't start Ollama."""
    name, _, tag = model.partition(":")
    root = Path(os.environ.get("OLLAMA_MODELS", Path.home() / ".ollama" / "models"))
    ns = "" if "/" in name else "library/"
    return (root / "manifests" / "registry.ollama.ai" / f"{ns}{name}" / (tag or "latest")).exists()


def tiers() -> list[dict]:
    s = settings()
    return [{"tier": t, "label": label, "model": s[t], "size": size, "installed": installed(s[t])}
            for t, label, size in TIERS]


def _post(path: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(settings()["ollama_url"].rstrip("/") + path,
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _chat(task: str, messages: list[dict], tier: str, timeout: float, fmt: dict | None,
          max_tokens: int | None = None) -> tuple[str, dict]:
    """One non-streaming chat call. Returns (content, info). Raises Unavailable on any failure."""
    model = settings()[tier]
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731
    if not installed(model):
        _log(model, task, 0, None, None, False, "not downloaded")
        raise Unavailable(f"{model} isn't downloaded")
    try:
        ensure_server()
    except Unavailable as e:
        _log(model, task, ms(), None, None, False, str(e))
        raise
    body = {"model": model, "stream": False, "think": False, "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0.3, "num_ctx": NUM_CTX}, "messages": messages}
    if max_tokens:
        body["options"]["num_predict"] = max_tokens
    if fmt:
        body["format"] = fmt
    try:
        resp = _post("/api/chat", body, timeout)
        content = resp["message"]["content"]
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as e:
        _log(model, task, ms(), None, None, False, repr(e))
        raise Unavailable(str(e)) from e
    info = {"model": model, "ms": ms(), "tokens_in": resp.get("prompt_eval_count"),
            "tokens_out": resp.get("eval_count")}
    _log(model, task, info["ms"], info["tokens_in"], info["tokens_out"], True)
    return content, info


def local_json(task: str, system: str, user: str, schema: dict, tier: str = "fast",
               timeout: float = 30) -> dict:
    """Ask the local model for JSON matching `schema`. Raises Unavailable on any failure."""
    content, _ = _chat(task, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                       tier, timeout, schema)
    try:
        return json.loads(content)
    except ValueError as e:
        raise Unavailable("model returned bad JSON") from e


def local_text(task: str, messages: list[dict], tier: str = "fast", timeout: float = 120,
               max_tokens: int = 2500) -> tuple[str, dict]:
    """Free-text chat. `messages` includes the system message. Raises Unavailable on any failure.
    Thinking-only models (the current qwen3:4b tag) write their reasoning before `</think>`
    whatever `think` says; only the part after it is returned. `max_tokens` caps the whole
    reply, reasoning included, so a ramble can't run on."""
    content, info = _chat(task, messages, tier, timeout, None, max_tokens)
    if "<think>" in content and "</think>" not in content or (
            "</think>" not in content and info["tokens_out"] and info["tokens_out"] >= max_tokens):
        raise Unavailable("the model ran out of room before answering")
    return content.split("</think>")[-1].strip(), info


def warm(tier: str = "fast") -> None:
    """Load a model ahead of use (the Ask drawer opening). Same options as real calls, or
    Ollama would reload it. Silent on failure: the real call reports the problem."""
    model = settings()[tier]
    if not installed(model):
        return
    try:
        ensure_server()
        _post("/api/generate", {"model": model, "keep_alive": KEEP_ALIVE, "options": {"num_ctx": NUM_CTX}}, 60)
    except (Unavailable, urllib.error.URLError, OSError, ValueError):
        log.info("warm %s failed", model)
