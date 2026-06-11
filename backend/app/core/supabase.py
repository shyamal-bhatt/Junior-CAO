"""
core/supabase.py
────────────────
Supabase client initialization.
"""

from supabase import create_client, Client
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

_supabase_client: Client | None = None

def get_supabase_client() -> Client:
    """
    Returns a singleton instance of the Supabase Client.
    """
    global _supabase_client
    if _supabase_client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            logger.warning("Supabase URL or Key is not configured. Client initialization might fail or use defaults.")
        
        logger.info("Initializing Supabase client with URL: %s", settings.SUPABASE_URL)
        _supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    
    return _supabase_client
