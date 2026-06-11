import asyncio
import httpx
from app.core.config import get_settings

async def check():
    settings = get_settings()
    url = f"{settings.NANGO_SERVER_URL}/sync/status"
    headers = {
        "Authorization": f"Bearer {settings.NANGO_SECRET_KEY}"
    }
    params = {
        "provider_config_key": "github",
        "connection_id": "63fe421a-0b68-43ef-b7e0-2554ec7ad174"
    }
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers, params=params)
        print(f"Sync status code: {res.status_code}")
        print(res.text)

if __name__ == "__main__":
    asyncio.run(check())
