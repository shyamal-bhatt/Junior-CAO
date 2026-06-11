"""
services/agent/guardrails.py
────────────────────────────
Input sanitization and validation — runs BEFORE the LangGraph graph is invoked.

Raises FastAPI HTTPException(400) on any failure so the error surfaces cleanly
to the client before any LLM tokens are spent.
"""

import re
import unicodedata

from fastapi import HTTPException, status

from app.core.logging import get_logger

logger = get_logger(__name__)

# Maximum allowed input length (characters)
MAX_INPUT_LENGTH = 2000

# Patterns that indicate a prompt injection attempt.
# Kept simple; extend as needed.
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore (all |previous |prior )?(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"\bsystem\s*:", re.IGNORECASE),
    re.compile(r"you are now\b", re.IGNORECASE),
    re.compile(r"disregard (your )?(previous |prior )?(instructions?|guidelines?)", re.IGNORECASE),
    re.compile(r"forget (everything|all|what)", re.IGNORECASE),
    re.compile(r"new (persona|role|identity|instructions?)\b", re.IGNORECASE),
]


def sanitize_and_validate(text: str) -> str:
    """
    Sanitize and validate a raw user input string.

    Steps
    -----
    1. Strip whitespace.
    2. Reject empty input.
    3. Enforce length cap.
    4. Normalize unicode (NFKC).
    5. Detect prompt injection patterns.

    Returns the cleaned string on success.
    Raises HTTPException(400) on any validation failure.
    """
    if not isinstance(text, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message must be a string.",
        )

    # 1. Strip
    text = text.strip()

    # 2. Empty check
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message cannot be empty.",
        )

    # 3. Length cap
    if len(text) > MAX_INPUT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Message exceeds maximum length of {MAX_INPUT_LENGTH} characters.",
        )

    # 4. Unicode normalize
    text = unicodedata.normalize("NFKC", text)

    # 5. Injection detection
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning("Prompt injection pattern detected: %r", text[:80])
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid input detected.",
            )

    return text
