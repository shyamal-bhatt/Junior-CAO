"""
core/logging.py
───────────────
Coloured, structured logger for the Junior CAO backend.

Log levels are rendered in distinct ANSI colours so they stand out
at a glance when tailing Docker / uvicorn output:

  DEBUG   → cyan
  INFO    → green
  WARNING → yellow
  ERROR   → red
  CRITICAL→ bold red

Usage anywhere in the app:
    from app.core.logging import get_logger
    logger = get_logger(__name__)

    logger.debug("Detailed trace info")
    logger.info("User 42 synced 7 records")
    logger.warning("Rate-limit threshold approaching")
    logger.error("Supabase timeout", exc_info=True)
    logger.critical("Application is in an unrecoverable state")
"""

import logging
import sys
from typing import Optional

# ── ANSI colour codes ─────────────────────────────────────────────────────────

import re

RESET = "\033[0m"
BOLD  = "\033[1m"

LEVEL_COLOURS: dict[str, str] = {
    "DEBUG":    "\033[36m",   # Cyan
    "INFO":     "\033[32m",   # Green
    "WARNING":  "\033[33m",   # Yellow
    "ERROR":    "\033[31m",   # Red
    "CRITICAL": "\033[1;31m", # Bold Red
}

TAG_COLOURS: dict[str, str] = {
    "EMBEDDING":         "\033[1;36m", # Bold Cyan
    "NORMALIZATION":     "\033[1;33m", # Bold Yellow
    "DATABASE":          "\033[1;35m", # Bold Magenta
    "RAW INGEST":        "\033[1;32m", # Bold Green
    "VALIDATION":        "\033[1;34m", # Bold Blue
    "ROUTING":           "\033[1;36m", # Bold Cyan
    "PARSING":           "\033[1;33m", # Bold Yellow
    "PIPELINE START":    "\033[1;32m", # Bold Green
    "TRACE":             "\033[1;30m", # Bold Dark Grey
    "PIPELINE COMPLETE": "\033[1;32m", # Bold Green
}


# ── Custom formatter ──────────────────────────────────────────────────────────

class ColouredFormatter(logging.Formatter):
    """
    Renders each log line with ANSI colour applied to the level name.
    Automatically colorizes bracketed uppercase tags like [EMBEDDING] in the message.
    """

    BASE_FMT = "%(asctime)s | {colour}%(levelname)-8s{reset} | %(name)s:%(lineno)d | %(message)s"
    DATE_FMT = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        original_msg = record.msg
        if isinstance(record.msg, str):
            def replace_tag(match):
                tag = match.group(1)
                color = TAG_COLOURS.get(tag, "\033[1;36m") # Default bold cyan
                return f"{color}[{tag}]{RESET}"
            
            # Match bracketed tags containing uppercase letters, spaces, hyphens, or underscores
            record.msg = re.sub(r"\[([A-Z0-9\s_/\-]+)\]", replace_tag, record.msg)

        colour = LEVEL_COLOURS.get(record.levelname, RESET)
        fmt = self.BASE_FMT.format(colour=colour, reset=RESET)
        formatter = logging.Formatter(fmt, datefmt=self.DATE_FMT)
        res = formatter.format(record)
        
        # Restore original message to avoid mutating it permanently
        record.msg = original_msg
        return res



# ── Plain formatter (for file handlers / structured logs) ────────────────────

PLAIN_FMT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"


# ── Root app logger ───────────────────────────────────────────────────────────

def _build_root_logger() -> logging.Logger:
    """
    Constructs and returns the single, shared root logger for the app.
    Called once at module-import time.
    """
    root = logging.getLogger("junior_cao")
    root.setLevel(logging.DEBUG)

    # Prevent duplicate handlers if module is re-imported (e.g. hot-reload)
    if root.handlers:
        return root

    # ── Console handler (stdout) ──────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(ColouredFormatter())

    root.addHandler(console_handler)

    # Silence noisy third-party loggers at WARNING level so our logs aren't drowned
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return root


_ROOT_LOGGER = _build_root_logger()


# ── Public API ────────────────────────────────────────────────────────────────

def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Return a child logger namespaced under 'junior_cao'.

    Args:
        name: Typically __name__ of the calling module.
              If None, returns the root app logger.

    Example:
        logger = get_logger(__name__)
    """
    if name is None:
        return _ROOT_LOGGER
    # Strip the 'app.' prefix for cleaner log lines (optional, cosmetic)
    short_name = name.removeprefix("app.")
    return _ROOT_LOGGER.getChild(short_name)
