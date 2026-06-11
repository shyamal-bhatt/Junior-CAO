"""
features/embeddings/service.py
───────────────────────────────
Text embeddings service.
Generates 1024-dimension vectors locally using the BAAI/bge-large-en-v1.5 model.
"""

from typing import List
from app.core.logging import get_logger

logger = get_logger(__name__)

# Global model container for lazy loading
_model = None

def _get_model():
    """Lazily loads the local SentenceTransformer model."""
    global _model
    if _model is None:
        logger.info("Initializing local SentenceTransformer model 'BAAI/bge-large-en-v1.5'...")
        from sentence_transformers import SentenceTransformer
        # Load local model (downloads on first use)
        _model = SentenceTransformer('BAAI/bge-large-en-v1.5')
        logger.info("Local SentenceTransformer model loaded successfully.")
    return _model

class EmbeddingService:
    """
    Handles generating text embeddings locally.
    """

    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generates a 1024-dimension vector for the input text using local BAAI/bge-large-en-v1.5 model.
        """
        if not text:
            vector = [0.0] * 1024
            logger.info("[EMBEDDING] Text chunk transformed. Vector Shape: (1024,).")
            return vector

        model = _get_model()
        
        # Run encoding (encode handles raw string or list of strings)
        # We run this in executor if needed, but simple CPU/GPU inference works directly
        embedding = model.encode(text, normalize_embeddings=True)
        
        # Convert numpy array to list of floats
        vector = [float(x) for x in embedding]

        # Print exact log statement matching the trace requirement
        logger.info("[EMBEDDING] Text chunk transformed. Vector Shape: (1024,).")
        return vector

# Singleton instance
embedding_service = EmbeddingService()
