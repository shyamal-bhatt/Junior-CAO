"""
features/embeddings/service.py
───────────────────────────────
Text embeddings service.
Generates 1536-dimension vectors using OpenAI's text-embedding-3-small model.
"""

import httpx
from typing import List
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

class EmbeddingService:
    """
    Handles generating text embeddings using OpenAI API.
    """

    def __init__(self):
        self.api_url = "https://api.openai.com/v1/embeddings"
        self.model = "text-embedding-3-small"
        self.api_key = settings.OPENAI_API_KEY

    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generates a 1536-dimension vector for the input text.
        Falls back to a mock vector if no OpenAI API key is configured.
        """
        if not text:
            # Return zero vector for empty text
            vector = [0.0] * 1536
            logger.info("[EMBEDDING] Text chunk transformed. Vector Shape: (1536,).")
            return vector

        if not self.api_key or self.api_key in ["", "your-openai-api-key-here"]:
            logger.warning("OPENAI_API_KEY is not configured. Generating a mock vector (1536,) for testing.")
            # Simple hash-deterministic mock vector generator for consistent testing
            import hashlib
            h = hashlib.sha256(text.encode("utf-8")).digest()
            vector = []
            for i in range(1536):
                # Deterministic float between -1.0 and 1.0
                val = ((h[i % len(h)] * (i + 1)) % 1000) / 500.0 - 1.0
                vector.append(val)
            # Ensure the signature logging is executed exactly
            logger.info("[EMBEDDING] Text chunk transformed. Vector Shape: (1536,).")
            return vector

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "input": text,
            "model": self.model,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(self.api_url, headers=headers, json=payload, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            embedding = data["data"][0]["embedding"]
            
            # Print exact log statement matching the trace requirement
            logger.info("[EMBEDDING] Text chunk transformed. Vector Shape: (1536,).")
            return embedding

# Singleton instance
embedding_service = EmbeddingService()
