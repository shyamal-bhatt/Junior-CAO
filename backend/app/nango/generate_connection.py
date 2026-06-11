"""
nango/generate_connection.py
────────────────────────────
Script to generate a Nango Connect Session link for google-calendar and google-mail.
"""

import httpx
import json
from app.core.config import get_settings

def generate_session():
    settings = get_settings()
    secret_key = settings.NANGO_SECRET_KEY
    server_url = settings.NANGO_SERVER_URL.rstrip("/")
    
    if not secret_key:
        print("Error: NANGO_SECRET_KEY is not configured in .env")
        return

    url = f"{server_url}/connect/sessions"
    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }
    # Create session for google-calendar and google-mail
    # Tagging with sam-google-user to identify the connection
    payload = {
        "allowed_integrations": ["google-calendar", "google-mail"],
        "tags": {
            "end_user_id": "sam-google-user"
        }
    }
    
    print(f"Creating Nango connect session at {url}...")
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        response.raise_for_status()
        response_data = response.json()
        connect_link = response_data.get("data", {}).get("connect_link")
        print("\n=====================================================================")
        print("🎉 NANGO CONNECTION LINK GENERATED SUCCESSFULLY")
        print("=====================================================================")
        print(f"Open the following URL in your browser to authorize:")
        print(f"\n{connect_link}\n")
        print("=====================================================================")
    except Exception as e:
        print(f"Failed to generate connection session: {e}")
        if 'response' in locals() and response is not None:
            print(f"Details: {response.text}")

if __name__ == "__main__":
    generate_session()
