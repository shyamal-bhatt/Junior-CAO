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

from langchain_core.messages import AIMessage, HumanMessage

from app.schemas.chat import (
    ActionRequest,
    ActionResponse,
    AgentResponse,
    ChatRequest,
    ChatResponse,
    ChatSession,
    ChatSessionCreate,
    ChatMessageResponse,
)
from app.services.chat_service import ChatService, close_http_client
from app.core.logging import get_logger
from app.core.supabase import get_supabase_client

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
    if payload.messages:
        logger.info("Received user message: %s", payload.messages[-1].content)

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
    if payload.messages:
        logger.info("Received streaming user message: %s", payload.messages[-1].content)
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



# ── Session Management Endpoints ──────────────────────────────────────────────

@router.get("/sessions", response_model=list[ChatSession], summary="List all chat sessions")
async def list_sessions():
    client = get_supabase_client()
    try:
        res = client.table("chat_sessions").select("*").order("updated_at", desc=True).execute()
        return res.data
    except Exception as e:
        logger.error("Failed to list chat sessions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error listing sessions: {e}"
        )


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse], summary="Get message history for a session")
async def get_session_messages(session_id: str):
    client = get_supabase_client()
    try:
        res = client.table("chat_messages").select("*").eq("session_id", session_id).order("created_at", desc=False).execute()
        return res.data
    except Exception as e:
        logger.error("Failed to get session messages for %s: %s", session_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error getting messages: {e}"
        )


@router.post("/sessions", response_model=ChatSession, summary="Create a new chat session")
async def create_session(payload: ChatSessionCreate):
    client = get_supabase_client()
    try:
        title = payload.title or "New Chat"
        res = client.table("chat_sessions").insert({"title": title}).execute()
        if not res.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create chat session: DB returned no data."
            )
        return res.data[0]
    except Exception as e:
        logger.error("Failed to create chat session: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error creating session: {e}"
        )


@router.delete("/sessions/{session_id}", summary="Delete a chat session")
async def delete_session(session_id: str):
    client = get_supabase_client()
    try:
        client.table("chat_sessions").delete().eq("id", session_id).execute()
        return {"status": "success", "deleted": session_id}
    except Exception as e:
        logger.error("Failed to delete chat session %s: %s", session_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error deleting session: {e}"
        )


# ── Agent endpoint ──────────────────────────────────────────────────────────

@router.post(
    "/agent",
    response_model=AgentResponse,
    summary="Run the LangGraph dual-stage agent (intent routing + grounded synthesis)",
)
async def agent_chat(
    payload: ChatRequest,
) -> AgentResponse:
    """
    Full LangGraph orchestration pipeline:

    1. **Guardrails** — sanitize & validate the user message.
    2. **Intent Router (Stage 1 LLM)** — decides which tools to call.
       The LLM may call `database_search` multiple times (different platforms / topics)
       in a single round, and may loop through up to 5 tool-calling rounds.
    3. **execute_tools** — runs all tool calls concurrently via asyncio.gather.
    4. **Synthesis Agent (Stage 2 LLM)** — produces a grounded answer from
       accumulated context chunks in the brutalist Junior CAO terminal voice.

    Returns the final answer plus the raw source chunks for optional frontend display.
    """
    from app.services.agent.guardrails import sanitize_and_validate
    from app.services.agent.graph import get_compiled_graph
    from app.core.config import get_settings

    settings = get_settings()

    # Validate we have at least one message
    if not payload.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="messages array cannot be empty.",
        )

    # Guardrails — run before touching the graph
    last_user_content = payload.messages[-1].content
    sanitized_query   = sanitize_and_validate(last_user_content)

    # ── Database Persistence (User Message) ───────────────────────────────────
    client = get_supabase_client()
    session_id = payload.session_id

    # Validate or auto-create session
    if session_id:
        try:
            check_session = client.table("chat_sessions").select("id").eq("id", session_id).execute()
            if not check_session.data:
                # Create the session if it doesn't exist
                client.table("chat_sessions").insert({"id": session_id, "title": "New Chat"}).execute()
        except Exception as e:
            logger.error("DB error checking/inserting session_id %s: %s", session_id, e)
    else:
        try:
            # Auto-create session
            title = last_user_content[:40] + ("..." if len(last_user_content) > 40 else "")
            new_sess = client.table("chat_sessions").insert({"title": title}).execute()
            if new_sess.data:
                session_id = new_sess.data[0]["id"]
            else:
                logger.error("DB failed to auto-create chat session, proceeding memory-only")
        except Exception as e:
            logger.error("DB error auto-creating session: %s", e)

    # Save user message to database
    if session_id:
        try:
            client.table("chat_messages").insert({
                "session_id": session_id,
                "role": "user",
                "content": last_user_content
            }).execute()
        except Exception as e:
            logger.error("DB error saving user message: %s", e)

    # Convert frontend ChatMessage list → LangChain message objects
    lc_messages: list = []
    for msg in payload.messages:
        if msg.role.value == "user":
            lc_messages.append(HumanMessage(content=msg.content))
        elif msg.role.value == "assistant":
            lc_messages.append(AIMessage(content=msg.content))
        # system messages from frontend are intentionally dropped

    # Initial LangGraph state
    initial_state = {
        "messages":          lc_messages,
        "user_query":        sanitized_query,
        "retrieved_context": [],
        "tool_calls_made":   0,
        "tool_error":        None,
        "final_response":    None,
    }

    try:
        graph  = get_compiled_graph()
        result = await graph.ainvoke(initial_state)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Agent pipeline error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent pipeline failed. Please try again.",
        )

    reply = result.get("final_response") or "> No response generated."
    logger.info(
        "POST /chat/agent — tool_rounds=%d sources=%d",
        result.get("tool_calls_made", 0),
        len(result.get("retrieved_context", [])),
    )

    # ── Database Persistence (Assistant Response) ─────────────────────────────
    if session_id:
        try:
            # Save assistant response
            client.table("chat_messages").insert({
                "session_id": session_id,
                "role": "assistant",
                "content": reply
            }).execute()

            # Update session title if it was default "New Chat" and update updated_at timestamp
            session_data = client.table("chat_sessions").select("title").eq("id", session_id).execute()
            if session_data.data and session_data.data[0].get("title") == "New Chat":
                title = last_user_content[:40] + ("..." if len(last_user_content) > 40 else "")
                client.table("chat_sessions").update({"title": title, "updated_at": "now()"}).eq("id", session_id).execute()
            else:
                client.table("chat_sessions").update({"updated_at": "now()"}).eq("id", session_id).execute()
        except Exception as e:
            logger.error("DB error saving assistant response or updating session: %s", e)

    return AgentResponse(
        reply=reply,
        model=settings.OPENROUTER_DEFAULT_MODEL,
        sources=result.get("retrieved_context", []),
        tool_rounds=result.get("tool_calls_made", 0),
        session_id=session_id,
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
