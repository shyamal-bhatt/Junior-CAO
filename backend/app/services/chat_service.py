"""
services/chat_service.py
────────────────────────
OpenRouter LLM integration — Layer 2 (The Brain).

Handles:
  - Standard chat completion (single turn, non-streaming)
  - Streaming SSE chat completion
  - Quick-action completions (search, summarize, create-task)

Rules:
  ✅ All LLM communication lives here
  ✅ Calls OpenRouter REST API directly via httpx (no OpenAI SDK needed)
  ❌ Does NOT know about HTTP request/response objects
  ❌ Never imported directly by main.py — only by routers
"""

import json
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.chat import (
    ActionRequest,
    ActionResponse,
    ActionType,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Role,
)

logger   = get_logger(__name__)
settings = get_settings()

# OpenRouter base URL
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# HTTP/2-capable async client reused across requests
_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return (or lazily create) the shared async HTTP client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
            http2=True,
        )
    return _client


async def close_http_client() -> None:
    """Called on app shutdown to gracefully close the client."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        logger.info("HTTP client closed")


# ── System prompt builder ──────────────────────────────────────────────────────

def _build_system_prompt(context: str | None = None) -> str:
    base = (
        "You are Junior CAO, a brutalist, no-nonsense AI assistant embedded in a "
        "minimalist dot-matrix terminal overlay. "
        "Respond concisely and in character — prefix assistant outputs with '> '. "
        "Avoid markdown formatting; prefer plain terminal-style text. "
        "Be direct, efficient, and slightly terse — like a command-line tool."
    )
    if context:
        base += f"\n\nCurrent context captured by the user: {context}"
    return base


# ── Shared request builder ────────────────────────────────────────────────────

def _build_openrouter_payload(
    model: str,
    messages: list[dict],
    stream: bool = False,
) -> dict:
    return {
        "model":    model,
        "messages": messages,
        "stream":   stream,
    }


def _build_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "HTTP-Referer":  settings.APP_SITE_URL,
        "X-Title":       settings.APP_NAME,
        "Content-Type":  "application/json",
    }


# ── Main service class ────────────────────────────────────────────────────────

class ChatService:
    """Encapsulates all LLM calls to OpenRouter."""

    # ── Standard (non-streaming) completion ──────────────────────────────────

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        Send the full conversation history to OpenRouter and return one reply.
        """
        logger.info(
            "chat() → model=%s messages=%d context=%s",
            request.model,
            len(request.messages),
            bool(request.context),
        )

        openrouter_messages = self._prepare_messages(request.messages, request.context)
        payload = _build_openrouter_payload(request.model, openrouter_messages, stream=False)

        logger.debug("Sending %d messages to OpenRouter", len(openrouter_messages))

        response = await get_http_client().post(
            _OPENROUTER_URL,
            headers=_build_headers(),
            json=payload,
        )
        response.raise_for_status()

        data  = response.json()
        reply = data["choices"][0]["message"]["content"]
        usage = data.get("usage")

        logger.info("LLM reply received — tokens_used=%s", usage)
        return ChatResponse(reply=reply, model=request.model, usage=usage)

    # ── Streaming completion ──────────────────────────────────────────────────

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """
        Stream the LLM response as Server-Sent Events.
        Yields SSE-formatted strings: 'data: {...}\\n\\n'
        The caller (router) wraps this in a StreamingResponse.
        """
        logger.info(
            "chat_stream() → model=%s messages=%d",
            request.model,
            len(request.messages),
        )

        openrouter_messages = self._prepare_messages(request.messages, request.context)
        payload = _build_openrouter_payload(request.model, openrouter_messages, stream=True)

        async with get_http_client().stream(
            "POST",
            _OPENROUTER_URL,
            headers=_build_headers(),
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if raw == "[DONE]":
                    logger.debug("SSE stream complete")
                    yield "data: [DONE]\n\n"
                    break
                try:
                    chunk = json.loads(raw)
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta:
                        yield f"data: {json.dumps({'content': delta['content']})}\n\n"
                except (json.JSONDecodeError, KeyError):
                    logger.warning("Skipping malformed SSE chunk: %s", raw)

    # ── Quick-action completions ──────────────────────────────────────────────

    async def run_action(self, request: ActionRequest) -> ActionResponse:
        """
        Execute a quick-action (SEARCH DB / SUMMARIZE / CREATE TASK).
        Each action injects a specialised system prompt that shapes the LLM's response.
        """
        logger.info("run_action() → action=%s model=%s", request.action, request.model)

        action_system = self._action_system_prompt(request.action, request.context)
        history = self._prepare_messages(request.messages, context=None)

        # Inject the action-specific system message at the front
        messages = [{"role": "system", "content": action_system}, *history]

        payload = _build_openrouter_payload(request.model, messages, stream=False)

        response = await get_http_client().post(
            _OPENROUTER_URL,
            headers=_build_headers(),
            json=payload,
        )
        response.raise_for_status()

        data   = response.json()
        result = data["choices"][0]["message"]["content"]

        logger.info("Action '%s' complete", request.action)
        return ActionResponse(action=request.action, result=result, model=request.model)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _prepare_messages(
        self,
        messages: list[ChatMessage],
        context: str | None,
    ) -> list[dict]:
        """
        Convert Pydantic ChatMessage list → OpenRouter message dicts,
        prepending the system prompt.
        """
        system = {"role": "system", "content": _build_system_prompt(context)}
        history = [{"role": m.role.value, "content": m.content} for m in messages]
        return [system, *history]

    def _action_system_prompt(self, action: ActionType, context: str | None) -> str:
        ctx_note = f" Current context: {context}." if context else ""

        prompts: dict[ActionType, str] = {
            ActionType.SEARCH: (
                f"You are a database search assistant.{ctx_note} "
                "The user wants to query their Supabase project data. "
                "Summarise what data would be relevant and how you would retrieve it. "
                "Prefix your response with '> SEARCH DB ::'. Keep it under 80 words."
            ),
            ActionType.SUMMARIZE: (
                f"You are a context summariser.{ctx_note} "
                "Condense the conversation so far into a concise bullet-point summary. "
                "Prefix with '> SUMMARIZE ::'. Maximum 5 bullets."
            ),
            ActionType.TASK: (
                f"You are a task-creation assistant.{ctx_note} "
                "Extract a clear, actionable task from the conversation and format it as: "
                "'> CREATE TASK :: [TITLE] — [brief description]'. "
                "One task only. No extra commentary."
            ),
        }
        return prompts[action]
