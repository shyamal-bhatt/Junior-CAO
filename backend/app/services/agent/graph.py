"""
services/agent/graph.py
───────────────────────
LangGraph state machine for the Junior CAO dual-stage agent pipeline.

Graph topology
──────────────

  [intent_router] ──→ should_continue? ──→ "tools"     → [execute_tools] ──┐
                                       └→ "synthesis"  → [synthesis_agent] → END
                                                                 ↑
                                              execute_tools loops back ──────┘

Nodes
─────
intent_router    Stage 1 LLM (tool_choice="required") — decides which tools to call.
                 May emit multiple parallel tool calls in a single turn.
execute_tools    Pure Python — runs all tool calls concurrently (asyncio.gather).
                 Accumulates results into state.retrieved_context.
synthesis_agent  Stage 2 LLM (no tools) — generates the final grounded answer.

Safety cap: MAX_TOOL_ROUNDS = 5. If the LLM calls tools more than 5 times,
the graph forces transition to synthesis with whatever context was gathered.

The compiled graph is a singleton — use get_compiled_graph() everywhere.
"""

import asyncio
import json

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.agent.prompts.intent_router import INTENT_ROUTER_PROMPT
from app.services.agent.prompts.synthesis import SYNTHESIS_PROMPT
from app.services.agent.state import AgentState
from app.services.agent.tools.database_search import database_search
from app.services.agent.tools.definitions import TOOL_SCHEMAS

logger   = get_logger(__name__)
settings = get_settings()

# Maximum tool-calling rounds before forcing synthesis
MAX_TOOL_ROUNDS = 5

# ── LLM factory ──────────────────────────────────────────────────────────────

def _make_llm() -> ChatOpenAI:
    """Build a ChatOpenAI client pointed at OpenRouter."""
    return ChatOpenAI(
        model=settings.OPENROUTER_DEFAULT_MODEL,
        openai_api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": settings.APP_SITE_URL,
            "X-Title":      settings.APP_NAME,
        },
    )


# ── Context formatter (used by synthesis node) ────────────────────────────────

def _format_context(chunks: list[dict]) -> str:
    """
    Convert retrieved chunk dicts into a readable block for the synthesis LLM.
    Each chunk is numbered and labelled with its source.
    """
    if not chunks:
        return "No data retrieved from the knowledge base."

    parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        platform   = (chunk.get("platform") or "unknown").upper()
        title      = chunk.get("title") or "Untitled"
        author     = chunk.get("author") or "Unknown"
        created_at = chunk.get("created_at") or ""
        text       = chunk.get("chunk_text") or ""
        similarity = chunk.get("similarity")
        sim_label  = f" [score: {similarity:.2f}]" if similarity is not None else ""

        parts.append(
            f"[{i}] {platform} | {title} | by {author} | {created_at}{sim_label}\n"
            f"{text}"
        )

    return "\n\n---\n\n".join(parts)


# ── Graph node functions ───────────────────────────────────────────────────────

async def _intent_router_node(state: AgentState, llm_router: ChatOpenAI) -> dict:
    """
    Stage 1 — Intent Router.
    Calls the LLM with tool_choice='required' so it MUST output tool calls.
    Returns the AI message (with tool_calls) to be appended to state.messages.
    """
    logger.info(
        "intent_router: round=%d messages=%d",
        state["tool_calls_made"],
        len(state["messages"]),
    )
    system_msg = SystemMessage(content=INTENT_ROUTER_PROMPT)
    response: AIMessage = await llm_router.ainvoke(
        [system_msg, *state["messages"]]
    )
    logger.debug(
        "intent_router: tool_calls=%s",
        [tc["name"] for tc in (response.tool_calls or [])],
    )
    return {"messages": [response]}


async def _execute_tools_node(state: AgentState) -> dict:
    """
    Execute all tool calls from the last AI message concurrently.

    - `no_tool_needed` calls are skipped (they are routing signals only).
    - `database_search` calls run in parallel via asyncio.gather.
    - Errors are caught per-call; failures don't abort the whole round.
    - ToolMessage results are appended to messages so the next intent_router
      turn has full context to decide whether to search again.
    """
    last_msg: AIMessage = state["messages"][-1]
    tool_calls = last_msg.tool_calls or []

    # Filter to only the real executable tools
    search_calls = [tc for tc in tool_calls if tc["name"] == "database_search"]

    logger.info(
        "execute_tools: %d database_search call(s) this round",
        len(search_calls),
    )

    # ── Run all database_search calls concurrently ────────────────────────────
    async def _run_one(tc: dict) -> tuple[str, list[dict], str | None]:
        """Returns (tool_call_id, results, error_str_or_None)."""
        call_id = tc["id"]
        args    = tc["args"]  # already parsed dict from langchain
        try:
            results = await database_search(
                query         = args.get("query", ""),
                platform      = args.get("platform", "any"),
                status_filter = args.get("status_filter"),
                author_filter = args.get("author_filter"),
                top_k         = int(args.get("top_k", 5)),
            )
            return (call_id, results, None)
        except Exception as exc:
            logger.error("database_search failed for call %s: %s", call_id, exc)
            return (call_id, [], str(exc))

    gathered = await asyncio.gather(*[_run_one(tc) for tc in search_calls])

    # ── Build ToolMessages and accumulate context ────────────────────────────
    tool_messages: list[ToolMessage] = []
    new_context:   list[dict]        = []
    last_error:    str | None        = None

    for call_id, results, error in gathered:
        if error:
            last_error = error
            content    = f"Tool error: {error}. No results returned."
        elif results:
            new_context.extend(results)
            # Send a brief preview so the router can decide if more queries are needed
            preview = results[0]["chunk_text"][:200] if results[0].get("chunk_text") else ""
            content = (
                f"Retrieved {len(results)} result(s). "
                f"Top result preview: {preview}..."
            )
        else:
            content = "No results found for this query."

        tool_messages.append(
            ToolMessage(content=content, tool_call_id=call_id)
        )

    # Also emit ToolMessages for any no_tool_needed calls
    # (required by OpenAI API — every tool_call_id must have a ToolMessage)
    for tc in tool_calls:
        if tc["name"] == "no_tool_needed":
            tool_messages.append(
                ToolMessage(
                    content=f"Acknowledged: {tc['args'].get('reason', 'no search needed')}",
                    tool_call_id=tc["id"],
                )
            )

    return {
        "messages":          tool_messages,
        "retrieved_context": new_context,           # accumulated by _accumulate reducer
        "tool_calls_made":   state["tool_calls_made"] + 1,
        "tool_error":        last_error,
    }


async def _synthesis_node(state: AgentState, llm_synth: ChatOpenAI) -> dict:
    """
    Stage 2 — Grounded Synthesis Agent.
    Receives the original query + all accumulated context chunks.
    Returns the final answer string in Junior CAO brutalist terminal voice.
    """
    context_text = _format_context(state["retrieved_context"])
    logger.info(
        "synthesis: query=%r context_chunks=%d tool_rounds=%d",
        state["user_query"][:60],
        len(state["retrieved_context"]),
        state["tool_calls_made"],
    )

    system_msg = SystemMessage(content=SYNTHESIS_PROMPT)
    human_content = (
        f"User question: {state['user_query']}\n\n"
        f"Retrieved context ({len(state['retrieved_context'])} chunk(s)):\n\n"
        f"{context_text}"
    )
    response: AIMessage = await llm_synth.ainvoke(
        [system_msg, HumanMessage(content=human_content)]
    )
    return {"final_response": response.content}


# ── Routing logic ─────────────────────────────────────────────────────────────

def _should_continue(state: AgentState) -> str:
    """
    Conditional edge from intent_router.

    Returns 'synthesis' when:
      - Safety cap reached (tool_calls_made >= MAX_TOOL_ROUNDS)
      - LLM called no_tool_needed
      - LLM output no tool calls at all (shouldn't happen with tool_choice=required)

    Returns 'tools' when:
      - LLM output database_search call(s) — run them and loop back
    """
    # Safety cap — never spin forever
    if state["tool_calls_made"] >= MAX_TOOL_ROUNDS:
        logger.warning("Max tool rounds reached — forcing synthesis")
        return "synthesis"

    last_msg = state["messages"][-1]

    # No tool_calls attribute (shouldn't happen) → synthesis
    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return "synthesis"

    # no_tool_needed present → done searching
    for tc in last_msg.tool_calls:
        if tc["name"] == "no_tool_needed":
            logger.info("intent_router chose no_tool_needed — routing to synthesis")
            return "synthesis"

    return "tools"


# ── Graph builder ─────────────────────────────────────────────────────────────

def _build_graph():
    """Construct and compile the LangGraph state machine."""
    # Build LLMs
    llm        = _make_llm()
    llm_router = llm.bind_tools(TOOL_SCHEMAS, tool_choice="required")
    llm_synth  = llm  # same model, no tools bound

    # Partially apply LLMs into node functions (closures)
    async def intent_router_node(state: AgentState) -> dict:
        return await _intent_router_node(state, llm_router)

    async def synthesis_node(state: AgentState) -> dict:
        return await _synthesis_node(state, llm_synth)

    # Build graph
    graph = StateGraph(AgentState)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("execute_tools", _execute_tools_node)
    graph.add_node("synthesis_agent", synthesis_node)

    # Edges
    graph.set_entry_point("intent_router")
    graph.add_conditional_edges(
        "intent_router",
        _should_continue,
        {
            "tools":     "execute_tools",
            "synthesis": "synthesis_agent",
        },
    )
    # After tool execution always loop back to intent_router
    graph.add_edge("execute_tools", "intent_router")
    graph.add_edge("synthesis_agent", END)

    return graph.compile()


# ── Singleton accessor ────────────────────────────────────────────────────────

_compiled_graph = None


def get_compiled_graph():
    """
    Return the singleton compiled LangGraph instance.
    Compiled once on first call; reused for all subsequent requests.
    """
    global _compiled_graph
    if _compiled_graph is None:
        logger.info("Compiling LangGraph agent graph...")
        _compiled_graph = _build_graph()
        logger.info("LangGraph agent graph compiled.")
    return _compiled_graph
