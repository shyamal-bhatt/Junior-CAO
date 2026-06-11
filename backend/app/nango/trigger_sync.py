"""
nango/trigger_sync.py
─────────────────────
Triggers Nango syncs programmatically for Google Calendar and Gmail connections.
"""

import httpx
from app.core.config import get_settings

def trigger_nango_sync(integration_id: str, connection_id: str, sync_names: list[str]):
    settings = get_settings()
    secret_key = settings.NANGO_SECRET_KEY
    server_url = settings.NANGO_SERVER_URL.rstrip("/")
    
    if not secret_key:
        print("Error: NANGO_SECRET_KEY is not configured in .env")
        return

    url = f"{server_url}/sync/trigger"
    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }
    
    # Body for triggering sync
    payload = {
        "provider_config_key": integration_id,
        "connection_id": connection_id,
        "syncs": sync_names
    }
    
    print(f"Triggering sync in Nango for '{integration_id}' (Connection ID: {connection_id}, Syncs: {sync_names})...")
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        response.raise_for_status()
        print(f"Successfully triggered sync. Response: {response.json()}")
    except Exception as e:
        print(f"Failed to trigger sync: {e}")
        if 'response' in locals() and response is not None:
            print(f"Details: {response.text}")

if __name__ == "__main__":
    # Google Calendar connection ID
    calendar_conn = "853e32bf-d7dd-4a0f-8a95-b7276ce46495"
    # Gmail connection ID
    gmail_conn = "88f607dc-014e-4d4e-8cee-70213b062a82"
    
    print("=== Triggering Google Calendar Sync ===")
    trigger_nango_sync("google-calendar", calendar_conn, ["events"])
    
    print("\n=== Triggering Gmail Sync ===")
    trigger_nango_sync("google-mail", gmail_conn, ["messages"])

