"""Model router. Every call is logged to `llm_calls` with its time and token counts.

Local first: Ollama (Qwen3) runs on the Mac, free and offline. Callers always have a
plain-Python fallback, because the model may be off, slow, or say something unusable.
Claude runs through `claude -p` (Claude Code on Keenan's subscription), never the API directly.
"""

import atexit
import glob
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
# Claude models by alias, so each always means the newest Haiku / Sonnet / Opus.
CLAUDE_DEFAULTS = {"haiku": "haiku", "sonnet": "sonnet", "opus": "opus"}
CLAUDE_TIERS = [("haiku", "Haiku"), ("sonnet", "Sonnet"), ("opus", "Opus")]
# The Ask drawer's model switch: tier, short label, rough download size.
TIERS = [("fast", "4B", "2.5 GB"), ("medium", "8B", "5.2 GB"), ("big", "30B", "18.6 GB")]
KEEP_ALIVE = "5m"  # the model leaves memory (~3 GB) 5 min after its last use
# Context window in tokens. Ollama otherwise sizes it to the Mac's memory (262k here), which
# reserved 43 GB for a 3 GB model. Prompts here are ~500 tokens.
NUM_CTX = 4096


class Unavailable(Exception):
    """The model couldn't answer (Ollama not running, model missing, timeout, bad JSON)."""


def settings() -> dict:
    return {**DEFAULTS, **CLAUDE_DEFAULTS, **config.load().get("models", {})}


# ---------- the Ollama server: started on first use, stopped when Meliora quits ----------
# Battery: the Ollama app (menu-bar icon, updater) is never opened. Meliora runs only the
# bare `ollama serve`, and only once something actually needs the model.
#
# It's started through launchd (`launchctl submit`), not as a child process. When Meliora is
# opened from the Dock, an `ollama serve` it starts directly can't reach the GPU (Metal) and
# runs CPU-only, ~10x slower. The same binary handed to launchd gets the GPU.

LABEL = "com.keenan.meliora.ollama"
GPU_TRIES = 2
_server_lock = threading.Lock()
_owned = False  # Meliora submitted the launchd job, so it's ours to stop


def _up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/version", timeout=1):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _job_loaded() -> bool:
    return subprocess.run(["launchctl", "list", LABEL], capture_output=True).returncode == 0


def _remove_job() -> None:
    subprocess.run(["launchctl", "remove", LABEL], capture_output=True)  # SIGTERM; ollama exits cleanly


def ensure_server() -> None:
    """Start `ollama serve` if nothing is listening. Raises Unavailable if it can't."""
    global _owned
    s = settings()
    with _server_lock:
        if _up(s["ollama_url"]):
            _owned = _owned or _job_loaded()  # left running by a Meliora that crashed: adopt it
            return
        exe = s["ollama_bin"] if os.path.exists(s["ollama_bin"]) else shutil.which("ollama")
        if not exe:
            raise Unavailable("Ollama isn't installed")
        _remove_job()  # a stale job from a crash that isn't answering
        for attempt in range(1, GPU_TRIES + 1):
            device = _start(exe, s["ollama_url"])
            _owned = True
            if device != "cpu" or attempt == GPU_TRIES:
                break
            log.warning("ollama started without the GPU (attempt %d); restarting it", attempt)
            _remove_job()
            time.sleep(1)
        if device == "cpu":
            log.warning("ollama is running on the CPU only; answers will be slow")
        log.info("started ollama serve via launchd (%s)", device)


def _start(exe: str, url: str) -> str:
    """Submit `ollama serve` to launchd and wait until it answers. Returns "gpu", "cpu" or
    "unknown", read from the "inference compute" line it logs at startup."""
    log_path = config.DATA_DIR / "ollama.log"
    log_path.touch()
    offset = log_path.stat().st_size
    host = url.split("://", 1)[-1].rstrip("/")
    r = subprocess.run(["launchctl", "submit", "-l", LABEL, "-o", str(log_path), "-e", str(log_path), "--",
                        "/usr/bin/env", f"OLLAMA_HOST={host}", exe, "serve"], capture_output=True, text=True)
    if r.returncode != 0:
        raise Unavailable(f"launchctl submit failed: {r.stderr.strip()[:120]}")
    deadline = time.monotonic() + 20
    device = "unknown"
    while time.monotonic() < deadline:
        with open(log_path, "rb") as f:
            f.seek(offset)
            new = f.read().decode(errors="replace")
        line = next((ln for ln in new.splitlines() if '"inference compute"' in ln), None)
        if line:
            device = "cpu" if "library=cpu" in line else "gpu"
        if line and _up(url):
            return device
        time.sleep(0.25)
    _remove_job()
    raise Unavailable("ollama serve didn't come up")


def shutdown() -> None:
    """Stop the server if Meliora started it. An Ollama someone else started is left alone."""
    global _owned
    if _owned:
        _remove_job()
        log.info("stopped ollama serve")
    _owned = False


atexit.register(shutdown)


def _log(model: str, task: str, ms: int, tin, tout, ok: bool, detail: str = "", backend: str = "ollama") -> None:
    try:
        with db.session() as conn:
            conn.execute(
                "INSERT INTO llm_calls (at, backend, model, task, ms, tokens_in, tokens_out, ok, detail)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (db.now(), backend, model, task, ms, tin, tout, int(ok), detail[:200]))
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


# ---------- Claude (`claude -p`) ----------
# Billing: `claude -p` uses Keenan's Claude subscription only while ANTHROPIC_API_KEY is
# unset (with it set, Claude Code bills the API per token), so it's always removed here.
# Each call is one stateless question: no tools, no saved session, no CLAUDE.md or
# settings loaded, so the prompt is only what Meliora sends.

class Stopped(Unavailable):
    """The Stop button ended the call."""


_claude_lock = threading.Lock()
_claude_proc: subprocess.Popen | None = None


def stop_claude() -> bool:
    """Kill the running `claude -p`, if any. Tokens it already used still count."""
    with _claude_lock:
        proc = _claude_proc
    if proc and proc.poll() is None:
        proc.kill()
        return True
    return False


def claude_usage() -> dict:
    """Claude tokens (in + out) from the call log: today and the last 7 days."""
    with db.session() as conn:
        q = ("SELECT COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0), COUNT(*)"
             " FROM llm_calls WHERE backend = 'claude' AND at >= ?")
        today = conn.execute(q, (time.strftime("%Y-%m-%d"),)).fetchone()
        week = conn.execute(q, (time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * 86400)),)).fetchone()
    return {"today": today[0], "today_calls": today[1], "week": week[0], "week_calls": week[1]}


def claude_bin() -> str | None:
    """`claude` from config, PATH, the usual install spots, or the VS Code extension."""
    s = config.load().get("models", {}).get("claude_bin")
    if s and os.path.exists(os.path.expanduser(s)):
        return os.path.expanduser(s)
    home = Path.home()
    found = [shutil.which("claude"), str(home / ".local/bin/claude"), str(home / ".claude/local/claude"),
             "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
    for f in found:
        if f and os.path.exists(f):
            return f
    ext = sorted(glob.glob(str(home / ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude")),
                 key=lambda p: [int(x) if x.isdigit() else 0 for x in
                                p.split("claude-code-")[1].split("-")[0].split(".")])
    return ext[-1] if ext else None


def claude_tiers() -> list[dict]:
    s, ok = settings(), bool(claude_bin())
    return [{"tier": t, "label": label, "model": s[t], "installed": ok, "backend": "claude"} for t, label in CLAUDE_TIERS]


def claude_json(task: str, system: str, user: str, schema: dict, tier: str = "sonnet",
                timeout: float = 180) -> tuple[dict, dict]:
    """One Claude call that must answer as JSON matching `schema`. Returns (data, info).
    Raises Unavailable when offline, signed out, or the reply is unusable."""
    alias = settings()[tier]
    exe = claude_bin()
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731
    if not exe:
        _log(alias, task, 0, None, None, False, "claude not found", "claude")
        raise Unavailable("Claude Code isn't installed")
    cwd = config.DATA_DIR / "claude"  # empty folder: no project CLAUDE.md gets pulled in
    cwd.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    cmd = [exe, "-p", "--model", alias, "--output-format", "json", "--tools", "",
           "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
           "--system-prompt", system, "--json-schema", json.dumps(schema)]
    global _claude_proc
    with _claude_lock:
        proc = _claude_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE, text=True, cwd=cwd, env=env)
    try:
        stdout, stderr = proc.communicate(user, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        proc.kill()
        proc.communicate()
        _log(alias, task, ms(), None, None, False, "timeout", "claude")
        raise Unavailable("Claude took too long") from e
    finally:
        with _claude_lock:
            if _claude_proc is proc:
                _claude_proc = None
    if proc.returncode < 0:  # killed by stop_claude()
        _log(alias, task, ms(), None, None, False, "stopped", "claude")
        raise Stopped()
    r = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    try:
        out = json.loads(r.stdout) if r.stdout.strip() else {}
    except ValueError:
        out = {}
    usage = out.get("modelUsage") or {}
    model = next(iter(usage), alias)  # the full model name behind the alias
    tin = sum(u.get("inputTokens", 0) + u.get("cacheCreationInputTokens", 0) + u.get("cacheReadInputTokens", 0)
              for u in usage.values()) or None
    tout = sum(u.get("outputTokens", 0) for u in usage.values()) or None
    data = out.get("structured_output")
    if r.returncode != 0 or out.get("is_error") or not isinstance(data, dict):
        why = (out.get("result") or r.stderr or r.stdout or "no output").strip()[:200]
        _log(model, task, ms(), tin, tout, False, why, "claude")
        raise Unavailable(why)
    info = {"model": model, "ms": ms(), "tokens_in": tin, "tokens_out": tout}
    _log(model, task, info["ms"], tin, tout, True, "", "claude")
    return data, info
