"""
schemas/chat.py
───────────────
Pydantic models for the chat API.
These define the exact shape of data flowing between the frontend and backend.
"""

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ── Shared types ──────────────────────────────────────────────────────────────

class Role(str, Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"


class ChatMessage(BaseModel):
    """A single turn in the conversation history."""
    role: Role
    content: str


# ── Action types ──────────────────────────────────────────────────────────────

class ActionType(str, Enum):
    """
    Maps to the action buttons in the frontend ActionMenu / ActionPanel.
    search   → SEARCH DB
    summarize→ SUMMARIZE
    task     → CREATE TASK
    """
    SEARCH    = "search"
    SUMMARIZE = "summarize"
    TASK      = "task"


# ── Request schemas ───────────────────────────────────────────────────────────

from datetime import datetime

class ChatSessionCreate(BaseModel):
    title: str | None = None


class ChatSession(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime


class ChatRequest(BaseModel):
    """
    Payload the frontend sends for a standard chat turn.

    Fields:
        messages        Full conversation history (oldest → newest).
                        The last item is the user's latest message.
        context         Optional context blob captured by the "grab" button
                        (e.g. current org/project name).
        model           OpenRouter model slug to use.
                        Defaults to a fast, cheap model so the user can override.
        stream          Whether to request SSE streaming. False = single JSON response.
        session_id      Optional session ID to persist conversation in the database.
    """
    messages: list[ChatMessage] = Field(..., min_length=1)
    context:  str | None        = Field(None, description="Context captured via the grab button")
    model:    str               = Field("openai/gpt-4o-mini", description="OpenRouter model slug")
    stream:   bool              = Field(False)
    session_id: str | None      = Field(None, description="Optional DB session ID to persist conversation")


class ActionRequest(BaseModel):
    """
    Payload for quick-action buttons (SEARCH DB, SUMMARIZE, CREATE TASK).

    Fields:
        action          Which action to run.
        context         Current conversation context / captured text.
        messages        Recent message history so the LLM has background.
        model           OpenRouter model slug.
    """
    action:   ActionType
    context:  str | None         = None
    messages: list[ChatMessage]  = Field(default_factory=list)
    model:    str                = Field("openai/gpt-4o-mini")


# ── Response schemas ──────────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    """Single-turn (non-streaming) response from the LLM."""
    reply:            str
    model:            str
    usage: dict[str, Any] | None = None


class ActionResponse(BaseModel):
    """Response from a quick-action invocation."""
    action:  ActionType
    result:  str
    model:   str


class AgentResponse(BaseModel):
    """
    Response from the LangGraph agent pipeline (POST /chat/agent).

    Fields
    ------
    reply        Final grounded answer from the synthesis stage.
    model        OpenRouter model slug used.
    sources      Retrieved context chunks (list of dicts with chunk_text,
                 title, author, platform, status, created_at, similarity).
                 Empty list when no_tool_needed was chosen.
    tool_rounds  Number of tool-calling rounds the agent performed (0–5).
    session_id   The DB session ID used or created.
    """
    reply:       str
    model:       str
    sources:     list[dict[str, Any]] = []
    tool_rounds: int = 0
    session_id:  str | None = None


