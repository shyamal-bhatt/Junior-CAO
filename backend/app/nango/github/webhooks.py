"""
nango/github/webhooks.py
────────────────────────
FastAPI service logic to capture real incoming webhooks from Nango's GitHub integration.
"""

import json
from typing import List, Dict, Any
from fastapi import APIRouter, Request, Depends, HTTPException, status
from app.core.logging import get_logger
from app.core.supabase import get_supabase_client
from app.features.embeddings.service import embedding_service
from app.core.config import get_settings

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks/nango", tags=["Webhooks"])

# Configuration for tracked repositories
TRACKED_PROJECT_TAG = "Junior CAO"
UNTRACKED_FALLBACK_TAG = "Linkmate"
TRACKED_REPOSITORIES = {"junior-cao", "Junior-CAO"}


@router.post("", status_code=status.HTTP_200_OK)
async def handle_nango_global_webhook(request: Request, supabase_client = Depends(get_supabase_client)):
    """
    Global webhook receiver configured as the Webhook URL in Nango dashboard.
    Dispatches to the correct integration-specific processor based on providerConfigKey.
    """
    body_bytes = await request.body()
    logger.info(f"[RAW INGEST] Received global payload of {len(body_bytes)} bytes from Nango.")
    
    if not body_bytes:
        return {"status": "ignored", "reason": "empty payload"}
        
    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Nango payload JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # If this is a Nango sync notification (meaning it notifies us a sync finished, but does not contain records)
    webhook_type = payload.get("type")
    provider = payload.get("providerConfigKey") or payload.get("provider")
    connection_id = payload.get("connectionId")
    model_name = payload.get("model")

    if webhook_type == "sync" and provider == "github" and connection_id and model_name:
        logger.info(f"Detected Nango Sync Notification for model '{model_name}'. Fetching actual records from Nango API...")
        records = await fetch_nango_records(provider, connection_id, model_name)
        return await process_github_records(records, supabase_client)

    if provider == "github":
        response_results = payload.get("responseResults", {})
        records = []
        if isinstance(response_results, dict):
            # Flatten all model lists (e.g. Issue, PullRequest) into a single list of records
            for model_name, model_records in response_results.items():
                if isinstance(model_records, list):
                    records.extend(model_records)
        elif isinstance(response_results, list):
            records = response_results
            
        if not records:
            # Fallback to direct records structure
            records = payload.get("results", payload.get("data", [payload]))
            
        return await process_github_records(records, supabase_client)
    else:
        logger.warning(f"Webhook received for unsupported provider config key: '{provider}'. Skipping.")
        return {"status": "ignored", "reason": f"unsupported provider: {provider}"}


@router.post("/github", status_code=status.HTTP_200_OK)
async def handle_github_webhook(request: Request, supabase_client = Depends(get_supabase_client)):
    """
    Legacy/Direct route for GitHub-only webhooks.
    """
    body_bytes = await request.body()
    logger.info(f"[RAW INGEST] Received payload of {len(body_bytes)} bytes from source Nango GitHub.")

    if not body_bytes:
        return {"status": "ignored", "reason": "empty payload"}

    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Nango payload JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # If payload is a dict with records or data, extract it
    records: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        response_results = payload.get("responseResults", {})
        if isinstance(response_results, dict):
            for model_records in response_results.values():
                if isinstance(model_records, list):
                    records.extend(model_records)
        elif isinstance(response_results, list):
            records = response_results
            
        if not records:
            records = payload.get("results", payload.get("data", [payload]))
    
    return await process_github_records(records, supabase_client)


async def fetch_nango_records(provider: str, connection_id: str, model_name: str) -> List[Dict[str, Any]]:
    """
    Queries Nango's GET /records REST API to fetch actual synced records.
    """
    settings = get_settings()
    url = f"{settings.NANGO_SERVER_URL}/records"
    headers = {
        "Authorization": f"Bearer {settings.NANGO_SECRET_KEY}",
        "connection-id": connection_id,
        "provider-config-key": provider
    }
    params = {
        "model": model_name
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            records = data.get("records", [])
            logger.info(f"Successfully fetched {len(records)} records from Nango API for model '{model_name}'.")
            return records
    except Exception as e:
        logger.error(f"Failed to fetch records from Nango API: {e}")
        return []


async def process_github_records(records: List[Dict[str, Any]], supabase_client) -> Dict[str, Any]:
    """
    Helper function to process and insert GitHub records.
    """
    if not records:
        logger.info("No records found in GitHub payload. Skipping processing.")
        return {"status": "ok", "records_processed": 0}


    # 2. DATA BOUNDARIES: Restrict syncing to the last 30 active items
    # Sort by updated_at or created_at descending if available, or just keep order
    def get_sort_key(record: Dict[str, Any]) -> str:
        return record.get("updated_at") or record.get("created_at") or ""
    
    try:
        sorted_records = sorted(records, key=get_sort_key, reverse=True)
    except Exception:
        sorted_records = records

    target_records = sorted_records[:30]
    logger.info(f"Ingesting {len(target_records)} active GitHub items (limited to 30 max).")

    processed_count = 0

    for idx, item in enumerate(target_records):
        # Extract metadata from Nango GitHub payload
        item_id = str(item.get("id") or f"github-item-{idx}")
        
        # Support common keys sent by Nango templates (e.g. description/body, creator/author/login)
        title = item.get("title") or item.get("name") or "Untitled Issue/PR"
        body = item.get("body") or item.get("description") or ""

        
        # Extract author
        author_data = item.get("author") or item.get("user") or item.get("creator") or {}
        if isinstance(author_data, dict):
            author = author_data.get("login") or author_data.get("username") or "unknown"
        else:
            author = str(author_data)

        # Extract status / state
        status_val = item.get("status") or item.get("state") or "open"
        created_at = item.get("created_at")

        # Determine if repository is tracked
        repo_data = item.get("repository") or {}
        repo_name = ""
        if isinstance(repo_data, dict):
            repo_name = repo_data.get("name") or repo_data.get("full_name") or ""
        elif isinstance(repo_data, str):
            repo_name = repo_data

        # 3. Handle Untracked Repositories & Map project tag
        # If repo is not in tracked list, map its title to match the project_tag (e.g. 'Linkmate')
        is_tracked = False
        for tracked in TRACKED_REPOSITORIES:
            if tracked.lower() in repo_name.lower():
                is_tracked = True
                break

        if is_tracked:
            project_tag = TRACKED_PROJECT_TAG
        else:
            project_tag = UNTRACKED_FALLBACK_TAG
            # Map title to match corresponding project_tag (e.g., prefix or override title)
            title = f"[{UNTRACKED_FALLBACK_TAG}] {title}"

        platform = "github"
        body_length = len(body)

        # 4. NORMALIZATION LOGGING
        logger.info(
            f"[NORMALIZATION] Successfully extracted fields. "
            f"Standardized map: {{id: {item_id}, title: {title}, platform: {platform}, body_length: {body_length}}}."
        )

        # 5. EMBEDDING GENERATION
        # Route normalized text blocks to processing functions in features/embeddings
        embedding = await embedding_service.generate_embedding(body or title)

        # 6. TRANSACTIONAL DATABASE WRITE (UPSERT via external_id)
        # Save structural properties to raw_documents and float array to document_chunks simultaneously in a single transaction
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
                    "p_project_tag": project_tag,
                    "p_created_at": created_at,
                    "p_chunk_text": body[:1000] if body else title,
                    "p_embedding": embedding
                }
            ).execute()
            processed_count += 1
        except Exception as db_err:
            logger.error(f"Failed to write record {item_id} to Supabase: {db_err}")
            # Continue processing others rather than crash mid-payload
            continue

    return {
        "status": "success",
        "total_received": len(records),
        "processed_limit": len(target_records),
        "successfully_inserted": processed_count
    }
