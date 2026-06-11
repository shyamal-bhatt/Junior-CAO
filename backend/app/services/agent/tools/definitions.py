"""
services/agent/tools/definitions.py
────────────────────────────────────
OpenAI-format tool schemas passed to the LLM via bind_tools().

The intent_router LLM sees ONLY these definitions — it never has direct access
to the database.  Its job is to output tool_calls; Python executes them.

Tools
-----
database_search   → Query the Supabase knowledge base (may be called multiple times).
no_tool_needed    → Signal that no DB lookup is required; LLM proceeds to synthesis.
"""

# Raw OpenAI function-calling tool schemas.
# LangChain's .bind_tools() accepts this format directly.
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "database_search",
            "description": (
                "Search the Junior CAO knowledge base. "
                "The base contains emails (platform='gmail'), "
                "calendar events (platform='google-calendar'), "
                "and GitHub issues/PRs (platform='github'). "
                "Call this tool once per distinct search need. "
                "You MAY call it multiple times with different arguments "
                "if the question spans multiple sources or topics. "
                "Do NOT call it if you have already retrieved sufficient context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural language search query. Be specific — "
                            "e.g. 'TMLS listing price for 123 Main St' "
                            "rather than 'real estate'."
                        ),
                    },
                    "platform": {
                        "type": "string",
                        "enum": ["github", "gmail", "google-calendar", "any"],
                        "description": (
                            "Restrict search to one data source. "
                            "Use 'any' only when the source is unknown."
                        ),
                    },
                    "status_filter": {
                        "type": "string",
                        "description": (
                            "Optional. Filter by document status. "
                            "GitHub: 'open' | 'closed'. "
                            "Gmail: 'read' | 'unread'. "
                            "Calendar: 'confirmed' | 'tentative' | 'cancelled'."
                        ),
                    },
                    "author_filter": {
                        "type": "string",
                        "description": (
                            "Optional. Filter by author name or email fragment. "
                            "Case-insensitive partial match."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return. Default: 5. Max: 15.",
                    },
                },
                "required": ["query", "platform"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "no_tool_needed",
            "description": (
                "Call this when no database lookup is required. "
                "Use it for: greetings, general questions answerable from "
                "conversation history, clarifications, or small talk. "
                "This is ALSO your signal to stop searching and synthesize "
                "an answer once you have gathered enough context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief reason why no search is needed.",
                    }
                },
                "required": ["reason"],
            },
        },
    },
]
