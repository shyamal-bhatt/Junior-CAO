"""
nango/gmail/service.py
────────────────────────
Gmail service that interacts with the Gmail API via Nango's Proxy.
"""

from typing import Any, Dict
from app.nango.client import get_nango_client, NangoClient
from app.core.logging import get_logger

logger = get_logger(__name__)


class GmailService:
    """
    Handles operations with Gmail through Nango.
    """

    def __init__(self, nango_client: NangoClient = None):
        self.nango_client = nango_client or get_nango_client()
        self.integration_id = "google-mail"

    async def list_messages(self, connection_id: str) -> Dict[str, Any]:
        """
        Lists emails for the authenticated user.
        
        Args:
            connection_id: The connection ID configured in Nango.
        """
        logger.info(f"GmailService: Listing messages for connection '{connection_id}'")
        response = await self.nango_client.proxy_request(
            method="GET",
            integration_id=self.integration_id,
            connection_id=connection_id,
            path="/gmail/v1/users/me/messages",
            params={"maxResults": 10},
        )
        response.raise_for_status()
        return response.json()
