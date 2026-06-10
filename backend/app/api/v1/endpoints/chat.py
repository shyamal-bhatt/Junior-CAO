"""
api/v1/endpoints/chat.py
────────────────────────
Chat routes — Layer 1 (The Web Layer / Controller).

Endpoints:
  POST /api/v1/chat/         → Standard single-turn LLM response
  POST /api/v1/chat/stream   → Streaming SSE LLM response
  POST /api/v1/chat/action   → Quick-action (SEARCH DB / SUMMARIZE / CREATE TASK)

Rules:
  ✅ Validates HTTP payloads via Pydantic schemas
  ✅ Delegates ALL LLM logic to ChatService
  ✅ Handles HTTP error mapping (400 / 422 / 500 / 502)
  ❌ Contains NO business logic
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

import httpx

from app.schemas.chat import (
    ActionRequest,
    ActionResponse,
    ChatRequest,
    ChatResponse,
)
from app.services.chat_service import ChatService, close_http_client
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


# ── Dependency ────────────────────────────────────────────────────────────────

def get_chat_service() -> ChatService:
    return ChatService()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=ChatResponse, summary="Send a chat message")
async def send_message(
    payload: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    """
    Send the full conversation history to the LLM and receive a single reply.
    Use this for standard turn-based chat.

    The `messages` array must be ordered oldest → newest; the last item
    is the user's current message.
    """
    logger.info(
        "POST /chat — model=%s turns=%d stream=%s",
        payload.model,
        len(payload.messages),
        payload.stream,
    )

    # If the frontend sends stream=true in the body, redirect to streaming
    if payload.stream:
        return StreamingResponse(
            service.chat_stream(payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # Disable nginx buffering for SSE
            },
        )

    try:
        return await service.chat(payload)
    except httpx.HTTPStatusError as exc:
        _handle_openrouter_error(exc)
    except httpx.RequestError as exc:
        logger.error("Network error calling OpenRouter: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach the AI service. Please try again.",
        )


@router.post(
    "/stream",
    summary="Stream a chat response (SSE)",
    response_class=StreamingResponse,
)
async def stream_message(
    payload: ChatRequest,
    service: ChatService = Depends(get_chat_service),
):
    """
    Stream the LLM response token-by-token as Server-Sent Events.

    The client should consume the SSE stream and append each `content` chunk
    to the assistant bubble in real time.

    SSE format:
        data: {"content": "token"}\\n\\n
        data: [DONE]\\n\\n
    """
    logger.info(
        "POST /chat/stream — model=%s turns=%d",
        payload.model,
        len(payload.messages),
    )
    try:
        return StreamingResponse(
            service.chat_stream(payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control":    "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except httpx.HTTPStatusError as exc:
        _handle_openrouter_error(exc)
    except httpx.RequestError as exc:
        logger.error("Network error calling OpenRouter: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach the AI service. Please try again.",
        )


@router.post(
    "/action",
    response_model=ActionResponse,
    summary="Run a quick action (SEARCH DB / SUMMARIZE / CREATE TASK)",
)
async def run_action(
    payload: ActionRequest,
    service: ChatService = Depends(get_chat_service),
) -> ActionResponse:
    """
    Trigger one of the three quick-action buttons from the frontend overlay.

    - **search**    → Queries context and explains what DB data is relevant.
    - **summarize** → Condenses the conversation into bullet points.
    - **task**      → Extracts an actionable task from the conversation.
    """
    logger.info("POST /chat/action — action=%s model=%s", payload.action, payload.model)
    try:
        return await service.run_action(payload)
    except httpx.HTTPStatusError as exc:
        _handle_openrouter_error(exc)
    except httpx.RequestError as exc:
        logger.error("Network error calling OpenRouter for action=%s: %s", payload.action, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach the AI service. Please try again.",
        )


# ── Error helpers ─────────────────────────────────────────────────────────────

def _handle_openrouter_error(exc: httpx.HTTPStatusError) -> None:
    """Map OpenRouter HTTP errors to meaningful FastAPI exceptions."""
    code = exc.response.status_code
    try:
        detail = exc.response.json().get("error", {}).get("message", str(exc))
    except Exception:
        detail = str(exc)

    logger.error("OpenRouter returned HTTP %d: %s", code, detail)

    if code == 401:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid OpenRouter API key. Check your .env configuration.",
        )
    if code == 429:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="OpenRouter rate limit hit. Please wait a moment and retry.",
        )
    if code == 402:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="OpenRouter account has insufficient credits.",
        )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"AI service error: {detail}",
    )
