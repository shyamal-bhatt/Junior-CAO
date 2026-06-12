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

from datetime import datetime
import asyncio
import json
import time

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
from app.services.agent.prompts.intent_router import get_intent_router_prompt
from app.services.agent.prompts.synthesis import get_synthesis_prompt
from app.services.agent.state import AgentState
from app.services.agent.tools.database_search import database_search
from app.services.agent.tools.definitions import TOOL_SCHEMAS

logger   = get_logger(__name__)
settings = get_settings()

# Maximum tool-calling rounds before forcing synthesis
MAX_TOOL_ROUNDS = 5

# Visual dividers for the trace logs — easier to spot boundaries in the terminal
_DIV  = "─" * 64
_DIV2 = "═" * 64


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
    Each chunk is numbered and labelled with its source, including its full text
    body, external platform ID, and direct citation URL where available.
    """
    if not chunks:
        return "No data retrieved from the knowledge base."

    parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        platform   = (chunk.get("platform") or "unknown").lower()
        title      = chunk.get("title") or "Untitled"
        author     = chunk.get("author") or "Unknown"
        created_at = chunk.get("created_at") or ""
        text       = chunk.get("chunk_text") or ""
        body       = chunk.get("body") or ""
        external_id = chunk.get("external_id") or ""
        similarity = chunk.get("similarity")
        sim_label  = f" [score: {similarity:.2f}]" if similarity is not None else ""
        is_mock    = chunk.get("is_mock", False)
        mock_label = " [MOCK DATA]" if is_mock else ""

        # Construct direct citation URL
        citation_url = ""
        if title.startswith("Attachment:"):
            filename = title.replace("Attachment:", "").strip()
            # Link to a Gmail search for this attachment file name
            citation_url = f"https://mail.google.com/mail/u/0/#search/has%3Aattachment+filename%3A{filename}"
        elif platform == "gmail" and external_id:
            citation_url = f"https://mail.google.com/mail/u/0/#inbox/{external_id}"
        elif platform == "google-calendar" and external_id:
            citation_url = f"https://calendar.google.com/calendar/r/event/{external_id}"
        elif platform == "github" and external_id:
            if external_id.isdigit():
                citation_url = f"https://github.com/shyamal-bhatt/Junior-CAO/issues/{external_id}"
            else:
                import urllib.parse
                safe_q = urllib.parse.quote(external_id)
                citation_url = f"https://github.com/shyamal-bhatt/Junior-CAO/search?q={safe_q}"
        
        url_label = f" | citation_url: {citation_url}" if citation_url else ""

        text_content = text
        body_content = body or text
        if is_mock:
            text_content = f"⚠️ [MOCK DATA CONTENT]\n{text}\n⚠️ [END MOCK DATA CONTENT]"
            body_content = f"⚠️ [MOCK DATA CONTENT]\n{body or text}\n⚠️ [END MOCK DATA CONTENT]"

        parts.append(
            f"[{i}] {platform.upper()} | {title} | by {author} | {created_at}{sim_label}{url_label}{mock_label}\n"
            f"--- RELEVANT CHUNK TEXT ---\n{text_content}\n"
            f"--- FULL CONTENT / DETAILS ---\n{body_content}"
        )

    return "\n\n---\n\n".join(parts)



def _truncate(text: str, n: int = 120) -> str:
    """Truncate a string to n chars for log readability."""
    return text[:n] + "…" if len(text) > n else text


# ── Graph node functions ───────────────────────────────────────────────────────

async def _intent_router_node(state: AgentState, llm_router: ChatOpenAI) -> dict:
    """
    Stage 1 — Intent Router.
    Calls the LLM with tool_choice='required' so it MUST output tool calls.
    Returns the AI message (with tool_calls) to be appended to state.messages.
    """
    round_num = state["tool_calls_made"] + 1

    # ── ENTER log ─────────────────────────────────────────────────────────────
    logger.info(_DIV2)
    logger.info(
        "[ROUTING] STAGE 1 — Intent Router  |  Round %d / %d",
        round_num, MAX_TOOL_ROUNDS,
    )
    logger.info(_DIV2)
    logger.info("[ROUTING] Model          : %s", settings.OPENROUTER_DEFAULT_MODEL)
    logger.info("[ROUTING] Context window : %d messages in state", len(state["messages"]))
    logger.info("[ROUTING] User query     : %s", _truncate(state["user_query"]))
    current_time_str = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
    router_prompt = get_intent_router_prompt(current_time_str)

    logger.info(
        "[ROUTING] System prompt  : %s",
        _truncate(router_prompt.strip(), 200),
    )
    logger.info("[ROUTING] Tools offered  : %s", [t["function"]["name"] for t in TOOL_SCHEMAS])

    # Log the last few messages being sent for full context visibility
    logger.debug("[ROUTING] Full message history sent to LLM:")
    for i, msg in enumerate(state["messages"][-5:], 1):   # last 5 messages
        role    = getattr(msg, "type", "?")
        content = _truncate(str(getattr(msg, "content", "")), 200)
        logger.debug("[ROUTING]   [%d] %s: %s", i, role, content)

    # ── LLM call ──────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    system_msg = SystemMessage(content=router_prompt)
    response: AIMessage = await llm_router.ainvoke(
        [system_msg, *state["messages"]]
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # ── RESPONSE log ──────────────────────────────────────────────────────────
    tool_calls = response.tool_calls or []
    logger.info("[ROUTING] ← LLM responded in %dms", elapsed_ms)
    logger.info("[ROUTING] Tool calls decided: %d", len(tool_calls))
    for i, tc in enumerate(tool_calls, 1):
        args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
        logger.info(
            "[ROUTING]   [%d] %s(%s)",
            i, tc["name"], _truncate(args_str, 160),
        )

    if not tool_calls:
        logger.warning("[ROUTING] ⚠ LLM returned no tool calls (unexpected with tool_choice=required)")

    logger.info(_DIV)

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
    search_calls = [tc for tc in tool_calls if tc["name"] == "database_search"]

    # ── ENTER log ─────────────────────────────────────────────────────────────
    logger.info(_DIV2)
    logger.info(
        "[DATABASE] EXECUTE TOOLS  |  Round %d  |  %d database_search call(s)",
        state["tool_calls_made"] + 1, len(search_calls),
    )
    logger.info(_DIV2)
    for i, tc in enumerate(search_calls, 1):
        args = tc.get("args", {})
        logger.info(
            "[DATABASE]   Call [%d]  query=%r  platform=%s  status=%s  author=%s  project_tag=%s  sort_by=%s  top_k=%s",
            i,
            args.get("query", ""),
            args.get("platform", "any"),
            args.get("status_filter", "—"),
            args.get("author_filter", "—"),
            args.get("project_tag", "—"),
            args.get("sort_by", "similarity"),
            args.get("top_k", 5),
        )

    if not search_calls:
        logger.info("[DATABASE]   (no database_search calls to execute)")

    # ── Run all calls concurrently ─────────────────────────────────────────────
    async def _run_one(tc: dict, call_index: int) -> tuple[str, list[dict], str | None]:
        """Returns (tool_call_id, results, error_str_or_None)."""
        call_id = tc["id"]
        args    = tc["args"]
        t0      = time.perf_counter()
        try:
            results = await database_search(
                query         = args.get("query", ""),
                platform      = args.get("platform", "any"),
                status_filter = args.get("status_filter"),
                author_filter = args.get("author_filter"),
                project_tag   = args.get("project_tag"),
                sort_by       = args.get("sort_by", "similarity"),
                top_k         = int(args.get("top_k", 5)),
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "[DATABASE]   Call [%d] ✓  %d results in %dms",
                call_index, len(results), elapsed_ms,
            )
            if results:
                for j, r in enumerate(results[:3], 1):  # preview top 3
                    sim = r.get("similarity")
                    sim_str = f"{sim:.3f}" if sim is not None else "n/a"
                    logger.info(
                        "[DATABASE]     [%d.%d] sim=%s | %s | %s | %s",
                        call_index, j,
                        sim_str,
                        (r.get("platform") or "?").upper(),
                        _truncate(r.get("title") or "Untitled", 50),
                        _truncate(r.get("chunk_text") or "", 80),
                    )
            return (call_id, results, None)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.error(
                "[DATABASE]   Call [%d] ✗  FAILED in %dms: %s",
                call_index, elapsed_ms, exc,
            )
            return (call_id, [], str(exc))

    gathered = await asyncio.gather(
        *[_run_one(tc, i) for i, tc in enumerate(search_calls, 1)]
    )

    # ── Build ToolMessages and accumulate context ─────────────────────────────
    tool_messages: list[ToolMessage] = []
    new_context:   list[dict]        = []
    last_error:    str | None        = None

    for call_id, results, error in gathered:
        if error:
            last_error = error
            content    = f"Tool error: {error}. No results returned."
        elif results:
            new_context.extend(results)
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

    # Emit ToolMessages for no_tool_needed calls (OpenAI API requires it)
    for tc in tool_calls:
        if tc["name"] == "no_tool_needed":
            tool_messages.append(
                ToolMessage(
                    content=f"Acknowledged: {tc['args'].get('reason', 'no search needed')}",
                    tool_call_id=tc["id"],
                )
            )

    total_chunks_so_far = len(state["retrieved_context"]) + len(new_context)
    logger.info(
        "[DATABASE] Round complete — new chunks: %d | total accumulated: %d",
        len(new_context), total_chunks_so_far,
    )
    logger.info(_DIV)

    return {
        "messages":          tool_messages,
        "retrieved_context": new_context,
        "tool_calls_made":   state["tool_calls_made"] + 1,
        "tool_error":        last_error,
    }


async def _synthesis_node(state: AgentState, llm_synth: ChatOpenAI) -> dict:
    """
    Stage 2 — Grounded Synthesis Agent.
    Receives the original query + all accumulated context chunks.
    Returns the final answer string in Junior CAO brutalist terminal voice.
    """
    chunks = state["retrieved_context"]

    current_time_str = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
    synthesis_prompt = get_synthesis_prompt(current_time_str)

    # ── ENTER log ─────────────────────────────────────────────────────────────
    logger.info(_DIV2)
    logger.info(
        "[PIPELINE START] STAGE 2 — Synthesis Agent  |  %d tool rounds  |  %d context chunks",
        state["tool_calls_made"], len(chunks),
    )
    logger.info(_DIV2)
    logger.info("[PIPELINE START] Model       : %s", settings.OPENROUTER_DEFAULT_MODEL)
    logger.info("[PIPELINE START] User query  : %s", _truncate(state["user_query"]))
    logger.info(
        "[PIPELINE START] System prompt: %s",
        _truncate(synthesis_prompt.strip(), 200),
    )
    logger.info("[PIPELINE START] Context chunks being passed to LLM:")
    if chunks:
        for i, chunk in enumerate(chunks, 1):
            sim = chunk.get("similarity")
            logger.info(
                "[PIPELINE START]   [%d] sim=%-5s | %-12s | %-40s | %s",
                i,
                f"{sim:.3f}" if sim is not None else "n/a",
                (chunk.get("platform") or "?").upper(),
                _truncate(chunk.get("title") or "Untitled", 40),
                _truncate(chunk.get("chunk_text") or "", 80),
            )
    else:
        logger.info("[PIPELINE START]   (none — no_tool_needed was chosen)")

    # Check if a database search was performed by looking at the messages history
    search_performed = False
    for msg in state.get("messages", []):
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("name") == "database_search":
                    search_performed = True
                    break
        if search_performed:
            break

    # ── LLM call ──────────────────────────────────────────────────────────────
    context_text = _format_context(chunks)
    search_status = "Yes" if search_performed else "No"
    human_content = (
        f"User question: {state['user_query']}\n\n"
        f"Search Performed: {search_status}\n\n"
        f"Retrieved context ({len(chunks)} chunk(s)):\n\n"
        f"{context_text}"
    )
    logger.debug("[PIPELINE START] Full human message to synthesis LLM:\n%s", human_content)

    t0 = time.perf_counter()
    system_msg = SystemMessage(content=synthesis_prompt)
    response: AIMessage = await llm_synth.ainvoke(
        [system_msg, HumanMessage(content=human_content)]
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # ── RESPONSE log ──────────────────────────────────────────────────────────
    logger.info("[PIPELINE COMPLETE] ← Synthesis LLM responded in %dms", elapsed_ms)
    logger.info("[PIPELINE COMPLETE] Final answer:\n%s", response.content)
    logger.info(_DIV2)


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
        logger.warning(
            "[ROUTING] ⚠ MAX_TOOL_ROUNDS (%d) reached — forcing synthesis", MAX_TOOL_ROUNDS
        )
        return "synthesis"

    last_msg = state["messages"][-1]

    # No tool_calls attribute → synthesis
    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        logger.info("[ROUTING] → No tool calls in response — routing to SYNTHESIS")
        return "synthesis"

    # no_tool_needed present → done searching
    for tc in last_msg.tool_calls:
        if tc["name"] == "no_tool_needed":
            reason = tc.get("args", {}).get("reason", "")
            logger.info(
                "[ROUTING] → no_tool_needed called (reason: %s) — routing to SYNTHESIS",
                _truncate(reason, 80),
            )
            return "synthesis"

    logger.info("[ROUTING] → database_search call(s) detected — routing to EXECUTE TOOLS")
    return "tools"


# ── Graph builder ─────────────────────────────────────────────────────────────

def _build_graph():
    """Construct and compile the LangGraph state machine."""
    llm        = _make_llm()
    llm_router = llm.bind_tools(TOOL_SCHEMAS, tool_choice="required")
    llm_synth  = llm

    async def intent_router_node(state: AgentState) -> dict:
        return await _intent_router_node(state, llm_router)

    async def synthesis_node(state: AgentState) -> dict:
        return await _synthesis_node(state, llm_synth)

    graph = StateGraph(AgentState)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("execute_tools", _execute_tools_node)
    graph.add_node("synthesis_agent", synthesis_node)

    graph.set_entry_point("intent_router")
    graph.add_conditional_edges(
        "intent_router",
        _should_continue,
        {
            "tools":     "execute_tools",
            "synthesis": "synthesis_agent",
        },
    )
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
