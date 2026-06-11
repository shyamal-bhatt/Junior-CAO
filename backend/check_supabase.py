import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.supabase import get_supabase_client

async def check():
    client = get_supabase_client()
    try:
        res = client.table("raw_documents").select("id, title, platform, project_tag").execute()
        documents = res.data
        print(f"\n=== Supabase Verification ===")
        print(f"Total documents in 'raw_documents': {len(documents)}")
        for idx, doc in enumerate(documents[:5]):
            print(f"  {idx + 1}. [{doc.get('platform')}] [{doc.get('project_tag')}] {doc.get('title')}")
            
        res_chunks = client.table("document_chunks").select("id").execute()
        print(f"Total chunks in 'document_chunks': {len(res_chunks.data)}")
    except Exception as e:
        print(f"Failed to query Supabase: {e}")

if __name__ == "__main__":
    asyncio.run(check())
