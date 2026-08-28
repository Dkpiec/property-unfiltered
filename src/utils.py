"""Shared helpers: logging (with secret redaction), config load, env,
tolerant JSON parsing, atomic manifest writes, and Telegram notifications.

All secrets are read from environment variables only. Nothing is hardcoded.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import yaml

# Repo root = parent of the src/ directory.
REPO_ROOT = Path(__file__).resolve().parent.parent

# Environment variable names whose values are secrets. Their values are
# redacted from any log line.
SECRET_KEYS = frozenset({
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "PEXELS_API_KEY",
    "PIXABAY_API_KEY",
    "YOUTUBE_CLIENT_SECRETS",
    "YOUTUBE_REFRESH_TOKEN",
    "YOUTUBE_ACCESS_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "GH_PAT",
    "HF_TOKEN",
})


# ── Environment helpers ────────────────────────────────────────────────
def getenv(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def getenv_required(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Required environment variable is not set: {key}")
    return val


def redact(text: str | Any) -> str:
    """Replace any known secret values inside text with [REDACTED]."""
    if text is None:
        return ""
    text = str(text)
    for key in SECRET_KEYS:
        val = os.environ.get(key)
        if val and val in text:
            text = text.replace(val, "[REDACTED]")
    return text


# ── Config helpers ─────────────────────────────────────────────────────
def load_config(rel_path: str) -> Any:
    """Load a YAML config (or raw text) from the repo root, by relative path."""
    path = REPO_ROOT / rel_path
    with open(path, "r", encoding="utf-8") as f:
        if path.suffix.lower() in (".yaml", ".yml"):
            return yaml.safe_load(f)
        return f.read()


def load_prompt(rel_path: str) -> str:
    return str(load_config(rel_path))


# ── Logging (with redaction) ───────────────────────────────────────────
class RedactFormatter(logging.Formatter):
    """Formatter that redacts secret values before emitting the record."""

    def format(self, record: logging.LogRecord) -> str:
        record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(a) for a in record.args)
        return super().format(record)


def setup_logging(name: str = "property-unfiltered",
                  log_dir: str | Path | None = None,
                  level: int = logging.INFO) -> logging.Logger:
    log_dir = Path(log_dir) if log_dir else REPO_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    fmt = RedactFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)

    file = RotatingFileHandler(log_dir / f"{name}.log",
                               maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(fmt)

    logger.addHandler(stream)
    logger.addHandler(file)
    return logger


# ── Tolerant JSON parsing ──────────────────────────────────────────────
def json_parse(text: str | Any) -> Any | None:
    """Parse JSON out of a model response, tolerating markdown fences and
    surrounding prose. Returns a dict/list or None on failure."""
    if text is None:
        return None
    text = str(text).strip()
    # Strip a ```json ... ``` fence if present
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: scan for the first balanced JSON object/array
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except (json.JSONDecodeError, ValueError):
                        return None
    return None


# ── Atomic manifest writes ─────────────────────────────────────────────
def write_manifest(path: str | Path, data: Any) -> Path:
    """Write JSON atomically (temp file + rename) to avoid partial reads."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    return path


def utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_year() -> int:
    from datetime import datetime
    return datetime.now().year


def inject_freshness(prompt: str) -> str:
    """Fill {current_year} / {today} placeholders so LLM prompts always use
    the current date (prevents stale-year content like '2024' in 2026)."""
    from datetime import datetime
    now = datetime.now()
    return (prompt
            .replace("{current_year}", str(now.year))
            .replace("{today}", now.strftime("%Y-%m-%d")))


# ── Telegram notifications ─────────────────────────────────────────────
def send_telegram_message(text: str, parse_mode: str = "HTML") -> None:
    """Send a message via the Telegram Bot API using env credentials.

    Uses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment.
    Raises RuntimeError on non-OK response. Never sends secrets (caller's
    responsibility to not include them in `text`).
    """
    import requests

    token = getenv("TELEGRAM_BOT_TOKEN")
    chat_id = getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code != 200:
        # Do not log the full response body (could echo secrets); log status only.
        raise RuntimeError(f"Telegram send failed with HTTP {resp.status_code}")
