"""
nango/client.py
───────────────
Core client for interacting with the Nango REST API and Nango Proxy.
"""

import httpx
from typing import Any, Dict, Optional
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger()


class NangoClient:
    """
    HTTP client wrapper for the Nango API.
    Handles communication with Nango using backend configurations.
    """

    def __init__(self):
        settings = get_settings()
        self.secret_key = settings.NANGO_SECRET_KEY
        self.server_url = settings.NANGO_SERVER_URL.rstrip("/")
        
        if not self.secret_key:
            logger.warning("NANGO_SECRET_KEY is not configured. Nango requests will fail.")

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    async def get_connections(self, integration_id: str, end_user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetches connections for a given integration.
        """
        url = f"{self.server_url}/connections"
        params = {"integrationId": integration_id}
        if end_user_id:
            params["tags[end_user_id]"] = end_user_id

        async with httpx.AsyncClient() as client:
            logger.info(f"Fetching Nango connections for integration: {integration_id}")
            response = await client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()

    async def proxy_request(
        self,
        method: str,
        integration_id: str,
        connection_id: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """
        Makes a proxy request to the external provider via Nango's Proxy.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            integration_id: The unique key of the Nango integration (e.g., 'github')
            connection_id: The connection ID (e.g., 'sam-github-connection')
            path: The relative API path on the external service (e.g., '/user')
            params: Optional query parameters for the external API.
            json_data: Optional JSON body.
            headers: Optional headers to forward to the external API.
        """
        # Nango Proxy endpoint format: {server_url}/proxy/{path}
        clean_path = path.lstrip("/")
        url = f"{self.server_url}/proxy/{clean_path}"

        proxy_headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Provider-Config-Key": integration_id,
            "Connection-Id": connection_id,
        }
        if headers:
            proxy_headers.update(headers)

        async with httpx.AsyncClient() as client:
            logger.info(f"Routing Nango Proxy request [{method}] -> {url} (Integration: {integration_id}, Connection: {connection_id})")
            response = await client.request(
                method=method,
                url=url,
                headers=proxy_headers,
                params=params,
                json=json_data,
            )
            return response


# Global Nango Client instance
_nango_client = None

def get_nango_client() -> NangoClient:
    global _nango_client
    if _nango_client is None:
        _nango_client = NangoClient()
    return _nango_client
