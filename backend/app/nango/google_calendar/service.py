"""
nango/google_calendar/service.py
────────────────────────────────
Google Calendar service that interacts with the Google Calendar API via Nango's Proxy.
"""

from typing import Any, Dict
from app.nango.client import get_nango_client, NangoClient
from app.core.logging import get_logger

logger = get_logger(__name__)


class GoogleCalendarService:
    """
    Handles operations with Google Calendar through Nango.
    """

    def __init__(self, nango_client: NangoClient = None):
        self.nango_client = nango_client or get_nango_client()
        self.integration_id = "google-calendar"

    async def list_events(self, connection_id: str) -> Dict[str, Any]:
        """
        Lists events for the primary calendar.
        
        Args:
            connection_id: The connection ID configured in Nango.
        """
        logger.info(f"GoogleCalendarService: Listing events for connection '{connection_id}'")
        response = await self.nango_client.proxy_request(
            method="GET",
            integration_id=self.integration_id,
            connection_id=connection_id,
            path="/calendars/primary/events",
            params={"maxResults": 10, "orderBy": "startTime", "singleEvents": "true"},
        )
        response.raise_for_status()
        return response.json()
