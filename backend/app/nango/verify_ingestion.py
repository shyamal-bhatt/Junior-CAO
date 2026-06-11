"""
nango/verify_ingestion.py
─────────────────────────
Simulates/mocks incoming Nango record ingestion for Google Calendar and Gmail to verify that the
normalization, embedding generation, and Supabase transactional database writes succeed.
"""

import asyncio
from app.core.supabase import get_supabase_client
from app.nango.google_calendar.webhooks import process_google_calendar_records
from app.nango.gmail.webhooks import process_gmail_records

# Sample Google Calendar event payload
mock_calendar_events = [
    {
        "id": "mock-calendar-event-111",
        "summary": "Junior CAO Sync & Architecture Align",
        "description": "Discussing how to ingest Gmail and Google Calendar webhooks using Nango.",
        "organizer": {
            "email": "organizer@example.com"
        },
        "status": "confirmed",
        "start": {
            "dateTime": "2026-06-12T10:00:00-04:00"
        }
    }
]

# Sample Gmail email payload
mock_gmail_messages = [
    {
        "id": "mock-gmail-message-222",
        "subject": "[Junior CAO] Deployment Plan and Setup",
        "body": "Hi team, we have successfully created the FastAPI normalizer endpoints and local sentence-transformers embedding models.",
        "from": "sender@example.com",
        "status": "unread",
        "date": "2026-06-11T14:30:22Z"
    }
]

async def main():
    print("Initializing Supabase client...")
    supabase_client = get_supabase_client()

    print("\n--- Testing Google Calendar Ingestion ---")
    calendar_res = await process_google_calendar_records(mock_calendar_events, supabase_client)
    print(f"Calendar Ingestion Result: {calendar_res}")

    print("\n--- Testing Gmail Ingestion ---")
    gmail_res = await process_gmail_records(mock_gmail_messages, supabase_client)
    print(f"Gmail Ingestion Result: {gmail_res}")

    print("\nChecking raw_documents table for inserted records...")
    res = supabase_client.table("raw_documents").select("*").in_("external_id", ["mock-calendar-event-111", "mock-gmail-message-222"]).execute()
    print(f"Records found in DB: {res.data}")
    
    # Clean up test records
    print("\nCleaning up test records from database...")
    supabase_client.table("raw_documents").delete().in_("external_id", ["mock-calendar-event-111", "mock-gmail-message-222"]).execute()
    print("Cleanup completed.")

if __name__ == "__main__":
    asyncio.run(main())
