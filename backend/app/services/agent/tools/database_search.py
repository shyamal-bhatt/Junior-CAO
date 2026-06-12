"""
services/agent/tools/database_search.py
────────────────────────────────────────
The concrete implementation of the `database_search` tool.

Flow
----
1. Run BAAI/bge-large-en-v1.5 to embed the query → 1024-dim float vector.
   (Wrapped in asyncio.to_thread so the CPU-bound model doesn't block the event loop.)
2. Call the `hybrid_search` Supabase RPC function with the embedding + filters.
   (Wrapped in asyncio.to_thread because supabase-py's sync client is used.)
3. Return list[dict] with keys: chunk_text, title, author, platform, status, created_at, similarity.

The LangGraph execute_tools node calls this function directly — never the LLM.
"""

import asyncio
import time
import logging

# pyrefly: ignore [missing-import]
from sentence_transformers import SentenceTransformer

from app.core.supabase import get_supabase_client
from app.core.logging import get_logger

logger = get_logger(__name__)

# Load embedding model once at import time (singleton).
# This is CPU/memory heavy — load once, reuse forever.
_embedding_model: SentenceTransformer | None = None


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading BAAI/bge-large-en-v1.5 embedding model...")
        _embedding_model = SentenceTransformer("BAAI/bge-large-en-v1.5")
        logger.info("Embedding model loaded.")
    return _embedding_model


def _embed_sync(query: str) -> list[float]:
    """Synchronous embedding call — runs in a thread pool."""
    model = _get_embedding_model()
    vector = model.encode(query, normalize_embeddings=True)
    return vector.tolist()


def _rpc_sync(
    embedding: list[float],
    query_text: str,
    platform: str | None,
    status_filter: str | None,
    author_filter: str | None,
    project_tag_filter: str | None,
    sort_by: str,
    top_k: int,
) -> list[dict]:
    """Synchronous Supabase RPC call — runs in a thread pool."""
    client = get_supabase_client()
    response = client.rpc(
        "hybrid_search",
        {
            "query_embedding":    embedding,
            "query_text":         query_text,
            "platform_filter":    platform,
            "status_filter":      status_filter,
            "author_filter":      author_filter,
            "project_tag_filter": project_tag_filter,
            "sort_by":            sort_by,
            "match_count":        min(top_k, 15),  # hard cap at 15
        },
    ).execute()
    return response.data or []


def _fill_missing_document_data_sync(results: list[dict]) -> list[dict]:
    """
    If the RPC did not return 'body' and 'external_id', query the raw_documents
    table to retrieve them for the matched records.
    """
    if not results:
        return results

    # Check if 'body', 'external_id' and 'is_mock' are already present in the first result
    first_res = results[0]
    if "body" in first_res and "external_id" in first_res and "is_mock" in first_res:
        return results

    logger.info("[DATABASE] 'body', 'external_id', or 'is_mock' missing from RPC output; executing fallback SELECT query on raw_documents")
    client = get_supabase_client()
    
    # Collect lists of titles and platforms to batch search
    titles = list({r.get("title") for r in results if r.get("title")})
    platforms = list({r.get("platform") for r in results if r.get("platform")})
    
    if not titles or not platforms:
        for r in results:
            if "body" not in r:
                r["body"] = r.get("chunk_text") or ""
            if "external_id" not in r:
                r["external_id"] = ""
            if "is_mock" not in r:
                r["is_mock"] = False
        return results

    try:
        # Fetch documents matching the titles and platforms
        db_res = client.table("raw_documents").select("title, platform, body, external_id, is_mock").in_("title", titles).in_("platform", platforms).execute()
        
        # Create lookup map keyed by (platform, title)
        lookup = {}
        for doc in db_res.data or []:
            key = (doc.get("platform"), doc.get("title"))
            lookup[key] = doc

        # Merge body, external_id, and is_mock into results
        for r in results:
            key = (r.get("platform"), r.get("title"))
            if key in lookup:
                r["body"] = lookup[key].get("body")
                r["external_id"] = lookup[key].get("external_id")
                r["is_mock"] = lookup[key].get("is_mock", False)
            else:
                r["body"] = r.get("chunk_text") or ""
                r["external_id"] = ""
                r["is_mock"] = False
    except Exception as e:
        logger.error("[DATABASE] Fallback query to raw_documents failed: %s", e)
        for r in results:
            if "body" not in r:
                r["body"] = r.get("chunk_text") or ""
            if "external_id" not in r:
                r["external_id"] = ""
            if "is_mock" not in r:
                r["is_mock"] = False
                
    return results


async def database_search(
    query:         str,
    platform:      str = "any",
    status_filter: str | None = None,
    author_filter: str | None = None,
    project_tag:   str | None = None,
    sort_by:       str = "similarity",
    top_k:         int = 5,
) -> list[dict]:
    """
    Semantic search over the Junior CAO knowledge base.

    Parameters
    ----------
    query         Natural language search string.
    platform      One of: 'github', 'gmail', 'google-calendar', 'any'.
    status_filter Optional document status filter (open/closed/read/unread/etc.).
    author_filter Optional author name fragment (case-insensitive ILIKE).
    project_tag   Optional project tag or repository name (e.g. 'Junior-CAO').
    sort_by       Ordering logic: 'similarity' (default) or 'date' (for chronological).
    top_k         Maximum results to return (capped at 15).

    Returns
    -------
    list[dict]  Each dict has: chunk_text, title, author, platform, status,
                created_at (ISO string), similarity (0–1 float), body (string),
                and external_id (string).
    """
    platform_arg = None if platform == "any" else platform

    logger.info(
        "[EMBEDDING] START  query=%r  platform=%s  status=%s  author=%s  project_tag=%s  sort_by=%s  top_k=%d",
        query, platform, status_filter or "—", author_filter or "—", project_tag or "—", sort_by, top_k,
    )

    # 1. Embed query
    t0 = time.perf_counter()
    embedding = await asyncio.to_thread(_embed_sync, query)
    embed_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "[EMBEDDING] DONE   %d-dim vector generated in %dms",
        len(embedding), embed_ms,
    )

    # 2. Supabase RPC
    logger.info(
        "[DATABASE] hybrid_search RPC  platform_filter=%s  status_filter=%s  author_filter=%s  project_tag_filter=%s  sort_by=%s  match_count=%d",
        platform_arg or "(all)", status_filter or "(all)", author_filter or "(all)", project_tag or "(all)", sort_by, min(top_k, 15),
    )
    t1 = time.perf_counter()
    results = await asyncio.to_thread(
        _rpc_sync,
        embedding,
        query,
        platform_arg,
        status_filter,
        author_filter,
        project_tag,
        sort_by,
        top_k,
    )
    rpc_ms = int((time.perf_counter() - t1) * 1000)

    # 3. Fallback/Fill missing columns
    if results:
        results = await asyncio.to_thread(_fill_missing_document_data_sync, results)
        sims = [r.get("similarity", 0) for r in results]
        logger.info(
            "[DATABASE] RPC returned %d rows in %dms  |  sim range: %.3f – %.3f",
            len(results), rpc_ms, min(sims), max(sims),
        )
    else:
        logger.info("[DATABASE] RPC returned 0 rows in %dms (no matches)", rpc_ms)

    return results

