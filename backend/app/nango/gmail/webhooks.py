"""
nango/gmail/webhooks.py
────────────────────────
Service logic to process and normalize Gmail messages received from Nango.
"""

from typing import List, Dict, Any
from app.core.logging import get_logger
from app.features.embeddings.service import embedding_service
from app.features.normalization.chunking import upsert_document_with_chunks

logger = get_logger(__name__)

TRACKED_PROJECT_TAG = "Junior CAO"


async def process_gmail_records(records: List[Dict[str, Any]], supabase_client) -> Dict[str, Any]:
    """
    Normalizes Gmail email records, generates embeddings, and saves to database.
    """
    if not records:
        logger.info("No records found in Gmail payload. Skipping processing.")
        return {"status": "ok", "records_processed": 0}

    # Sort/limit to last 30 active items
    def get_sort_key(record: Dict[str, Any]) -> str:
        return record.get("date") or record.get("created_at") or ""
    
    try:
        sorted_records = sorted(records, key=get_sort_key, reverse=True)
    except Exception:
        sorted_records = records

    target_records = sorted_records[:30]
    logger.info(f"Ingesting {len(target_records)} Gmail messages (limited to 30 max).")

    processed_count = 0

    for idx, item in enumerate(target_records):
        item_id = str(item.get("id") or f"gmail-{idx}")
        title = item.get("subject") or item.get("title") or "Untitled Email"
        body = item.get("body") or item.get("text") or item.get("snippet") or ""
        
        author = item.get("from") or item.get("sender") or "unknown"
        status_val = item.get("status") or "received"
        created_at = item.get("date") or item.get("created_at")

        platform = "gmail"
        body_length = len(body)

        # Resolve project tag dynamically based on text content
        content_lower = f"{title} {body}".lower()
        if "junior cao" in content_lower or "junior-cao" in content_lower or "cao" in content_lower:
            project_tag = "Junior-CAO"
        elif "linkmate" in content_lower:
            project_tag = "linkmate"
        else:
            project_tag = "general"

        # Normalization logging
        logger.info(
            f"[NORMALIZATION] Successfully extracted fields. "
            f"Standardized map: {{id: {item_id}, title: {title}, platform: {platform}, project_tag: {project_tag}, body_length: {body_length}}}."
        )

        try:
            await upsert_document_with_chunks(
                supabase_client=supabase_client,
                embedding_service=embedding_service,
                external_id=item_id,
                title=title,
                body=body,
                author=author,
                status=status_val,
                platform=platform,
                project_tag=project_tag,
                created_at=created_at
            )
            processed_count += 1
        except Exception as db_err:
            logger.error(f"Failed to write Gmail email {item_id} to Supabase: {db_err}")
            continue

    return {
        "status": "success",
        "total_received": len(records),
        "processed_limit": len(target_records),
        "successfully_inserted": processed_count
    }
