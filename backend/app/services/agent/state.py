"""
services/agent/state.py
───────────────────────
LangGraph state definition for the Junior CAO agent pipeline.

AgentState flows through every node in the graph.

Fields
------
messages          Full conversation including tool call/result turns.
                  Uses add_messages reducer so each node append rather than replaces.
user_query        The sanitized user question — set once at graph entry, never mutated.
retrieved_context Accumulates chunk dicts across all tool-call rounds.
                  Uses _accumulate reducer so results from every round are merged.
tool_calls_made   Safety counter — graph forces synthesis after MAX_TOOL_ROUNDS.
tool_error        Last tool error string, or None.
final_response    Set by the synthesis node; returned to the endpoint.
"""

from typing import TypedDict, Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


def _accumulate(left: list, right: list) -> list:
    """Reducer that appends new items to the existing list across graph updates."""
    return left + right


class AgentState(TypedDict):
    messages:          Annotated[list[BaseMessage], add_messages]
    user_query:        str
    retrieved_context: Annotated[list[dict], _accumulate]
    tool_calls_made:   int
    tool_error:        str | None
    final_response:    str | None
