"""
nango/github/service.py
────────────────────────
GitHub service that interacts with the GitHub API via Nango's Proxy.
"""

from typing import Any, Dict
from app.nango.client import get_nango_client, NangoClient
from app.core.logging import get_logger

logger = get_logger()


class GitHubService:
    """
    Handles operations with GitHub through Nango.
    """

    def __init__(self, nango_client: NangoClient = None):
        self.nango_client = nango_client or get_nango_client()
        self.integration_id = "github"

    async def get_user_info(self, connection_id: str) -> Dict[str, Any]:
        """
        Fetches the authenticated user's profile info from GitHub (GET /user).
        
        Args:
            connection_id: The connection ID configured in Nango (e.g. end-user's ID).
        """
        logger.info(f"GitHubService: Fetching user info for connection '{connection_id}'")
        response = await self.nango_client.proxy_request(
            method="GET",
            integration_id=self.integration_id,
            connection_id=connection_id,
            path="/user",
        )
        response.raise_for_status()
        return response.json()

    async def list_repositories(self, connection_id: str) -> list[Dict[str, Any]]:
        """
        Lists repositories for the authenticated user (GET /user/repos).
        
        Args:
            connection_id: The connection ID configured in Nango.
        """
        logger.info(f"GitHubService: Listing repositories for connection '{connection_id}'")
        response = await self.nango_client.proxy_request(
            method="GET",
            integration_id=self.integration_id,
            connection_id=connection_id,
            path="/user/repos",
            params={"sort": "updated", "per_page": 10},
        )
        response.raise_for_status()
        return response.json()
