"""
features/normalization/chunking.py
──────────────────────────────────
Recursive character text splitter and transaction-equivalent Python upsert implementation.
"""

from typing import List, Any, Dict
from app.core.logging import get_logger

logger = get_logger(__name__)

def split_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[str]:
    """
    Split text into chunks of up to chunk_size characters with chunk_overlap.
    Recursively splits by paragraph, sentence, word, and character.
    """
    if not text:
        return []
    
    separators = ["\n\n", "\n", " ", ""]
    
    def _split(text_to_split: str, separator_idx: int) -> List[str]:
        if len(text_to_split) <= chunk_size:
            return [text_to_split]
            
        separator = separators[separator_idx]
        splits = text_to_split.split(separator) if separator else list(text_to_split)
        
        chunks = []
        current_doc = ""
        
        for split in splits:
            if not current_doc:
                current_doc = split
            elif len(current_doc) + len(separator) + len(split) <= chunk_size:
                current_doc += separator + split
            else:
                chunks.append(current_doc)
                # handle overlap
                overlap_start = max(0, len(current_doc) - chunk_overlap)
                current_doc = current_doc[overlap_start:]
                if len(current_doc) + len(separator) + len(split) <= chunk_size:
                    current_doc += separator + split
                else:
                    current_doc = split
        if current_doc:
            chunks.append(current_doc)
            
        final_chunks = []
        for c in chunks:
            if len(c) > chunk_size and separator_idx + 1 < len(separators):
                final_chunks.extend(_split(c, separator_idx + 1))
            else:
                final_chunks.append(c)
        return final_chunks

    result = _split(text, 0)
    logger.info(f"[CHUNKING] Split text of length {len(text)} into {len(result)} chunks.")
    return result


async def upsert_document_with_chunks(
    supabase_client: Any,
    embedding_service: Any,
    external_id: str,
    title: str,
    body: str,
    author: str,
    status: str,
    platform: str,
    project_tag: str,
    created_at: str,
    is_mock: bool = False
) -> str:
    """
    Standard helper to upsert a document into raw_documents,
    split its body into semantic chunks, generate embeddings for each,
    and insert/update them in document_chunks.
    """
    # 1. Upsert document in raw_documents
    doc_payload = {
        "external_id": external_id,
        "title": title,
        "body": body,
        "author": author,
        "status": status,
        "platform": platform,
        "project_tag": project_tag,
        "created_at": created_at,
        "is_mock": is_mock
    }
    
    # Supabase UPSERT based on external_id
    res = supabase_client.table("raw_documents").upsert(
        doc_payload, on_conflict="external_id"
    ).execute()
    
    if not res.data:
        raise RuntimeError(f"Failed to upsert document {external_id}")
        
    doc_id = res.data[0]["id"]
    
    # 2. Chunk text
    text_to_chunk = body if body else title
    chunks = split_text(text_to_chunk)
    if not chunks:
        chunks = [title]
        
    # 3. Generate embeddings
    embeddings = []
    for chunk in chunks:
        emb = await embedding_service.generate_embedding(chunk)
        embeddings.append(emb)
        
    # 4. Clean old chunks
    supabase_client.table("document_chunks").delete().eq("document_id", doc_id).execute()
    
    # 5. Insert new chunks
    chunk_payloads = [
        {
            "document_id": doc_id,
            "chunk_text": chunk,
            "embedding": emb
        }
        for chunk, emb in zip(chunks, embeddings)
    ]
    supabase_client.table("document_chunks").insert(chunk_payloads).execute()
    
    return doc_id
