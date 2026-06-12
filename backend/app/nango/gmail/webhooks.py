"""
nango/gmail/webhooks.py
────────────────────────
Service logic to process and normalize Gmail messages received from Nango.
"""

from typing import List, Dict, Any
from app.core.logging import get_logger
from app.features.embeddings.service import embedding_service

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

        # Normalization logging
        logger.info(
            f"[NORMALIZATION] Successfully extracted fields. "
            f"Standardized map: {{id: {item_id}, title: {title}, platform: {platform}, body_length: {body_length}}}."
        )

        # Generate embeddings
        embedding = await embedding_service.generate_embedding(body or title)

        # Write to database (upsert)
        logger.info(
            f"[DATABASE] Writing row to SQL table 'raw_documents' and "
            f"inserting corresponding vector array to table 'document_chunks'."
        )

        try:
            supabase_client.rpc(
                "insert_document_with_chunks",
                {
                    "p_external_id": item_id,
                    "p_title": title,
                    "p_body": body,
                    "p_author": author,
                    "p_status": status_val,
                    "p_platform": platform,
                    "p_project_tag": "gmail",
                    "p_created_at": created_at,
                    "p_chunk_text": body[:1000] if body else title,
                    "p_embedding": embedding
                }
            ).execute()
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
