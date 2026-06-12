import asyncio
import httpx
from dotenv import load_dotenv
load_dotenv("/Users/sam/Projects/Junior CAO/backend/.env")

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.supabase import get_supabase_client

logger = get_logger(__name__)

async def trigger_sync():
    settings = get_settings()
    supabase = get_supabase_client()
    
    print("1. Wiping old documents from Supabase...")
    try:
        # Run security definer RPC to clear raw_documents (cascades to document_chunks)
        supabase.rpc("clear_all_documents", {}).execute()
        print("✓ Supabase raw_documents and document_chunks table successfully truncated.")
    except Exception as e:
        print(f"✗ Failed to clear documents: {e}")
        print("Attempting to run raw truncate policy...")
        
    print("\n2. Fetching active connections from Nango...")
    headers = {
        "Authorization": f"Bearer {settings.NANGO_SECRET_KEY}"
    }
    
    # We will trigger sync for all providers
    providers = ["github", "google-calendar", "google-mail"]
    
    async with httpx.AsyncClient() as client:
        # Fetch connections first to get the correct connection IDs
        url_connections = f"{settings.NANGO_SERVER_URL}/connections"
        
        for provider in providers:
            try:
                res = await client.get(url_connections, headers=headers, params={"integrationId": provider})
                if res.status_code == 200:
                    connections = res.json().get("connections", [])
                    print(f"\nProvider: {provider} — found {len(connections)} active connection(s)")
                    
                    for conn in connections:
                        conn_id = conn.get("connection_id")
                        print(f"  Triggering sync for connection: {conn_id} ...")
                        
                        # POST /sync/trigger to start a full sync
                        url_trigger = f"{settings.NANGO_SERVER_URL}/sync/trigger"
                        trigger_payload = {
                            "provider_config_key": provider,
                            "connection_id": conn_id,
                            "syncs": []
                        }
                        
                        trigger_res = await client.post(url_trigger, headers=headers, json=trigger_payload)
                        if trigger_res.status_code in [200, 201, 202]:
                            print(f"  ✓ Sync triggered successfully for {provider} ({conn_id}).")
                        else:
                            print(f"  ✗ Failed to trigger sync for {provider}: {trigger_res.status_code} - {trigger_res.text}")
                else:
                    print(f"✗ Failed to query connections for {provider}: {res.status_code} - {res.text}")
            except Exception as e:
                print(f"✗ Error communicating with Nango for {provider}: {e}")

if __name__ == "__main__":
    asyncio.run(trigger_sync())
