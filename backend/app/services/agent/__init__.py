"""
services/agent/__init__.py
──────────────────────────
LangGraph orchestration agent for Junior CAO.

Import graph components explicitly — do NOT eager-load here because
graph.py imports sentence-transformers which is large and slow to load.

Usage:
    from app.services.agent.graph import get_compiled_graph
"""

