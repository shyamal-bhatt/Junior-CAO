-- Supabase Database Schema DDL
-- Setup vector extension, metadata tables, and side-by-side vector chunks.

-- 1. Enable the pgvector extension to allow embedding storage and operations
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create raw_documents table to track document structural properties and metadata.
-- Designed generically to support multiple source platforms:
--   - GitHub (Issues/PRs): title (issue title), body (issue description), author (creator), platform='github'
--   - Gmail (Emails): title (subject), body (email body or parsed attachment text), author (sender), platform='gmail'
--   - Google Calendar (Events): title (event summary), body (description), author (organizer), platform='google-calendar'
CREATE TABLE IF NOT EXISTS public.raw_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT UNIQUE, -- Unique ID from source platform (e.g. github issue id) to prevent duplicates
    title TEXT,
    body TEXT,
    author TEXT,
    status TEXT, -- Status/State e.g. open/closed, read/unread, confirmed/tentative
    platform TEXT NOT NULL,
    project_tag TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE,
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Index for querying documents by platform and project tags
CREATE INDEX IF NOT EXISTS idx_raw_documents_platform_project_tag 
ON public.raw_documents (platform, project_tag);


-- 3. Create document_chunks table mapping chunks to parent raw_documents
CREATE TABLE IF NOT EXISTS public.document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES public.raw_documents(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(1024) NOT NULL
);

-- Index for fast cosine similarity search on the embedding vector
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding 
ON public.document_chunks USING hnsw (embedding vector_cosine_ops);

-- Transaction function to save metadata and chunk vector simultaneously in a single transactional step.
-- Uses ON CONFLICT on external_id to update existing documents (UPSERT) and prevent duplicates.
CREATE OR REPLACE FUNCTION public.insert_document_with_chunks(
    p_external_id TEXT,
    p_title TEXT,
    p_body TEXT,
    p_author TEXT,
    p_status TEXT,
    p_platform TEXT,
    p_project_tag TEXT,
    p_created_at TIMESTAMP WITH TIME ZONE,
    p_chunk_text TEXT,
    p_embedding VECTOR(1024)
) RETURNS UUID AS $$
DECLARE
    v_doc_id UUID;
BEGIN
    INSERT INTO public.raw_documents (external_id, title, body, author, status, platform, project_tag, created_at)
    VALUES (p_external_id, p_title, p_body, p_author, p_status, p_platform, p_project_tag, p_created_at)
    ON CONFLICT (external_id) 
    DO UPDATE SET 
        title = EXCLUDED.title,
        body = EXCLUDED.body,
        status = EXCLUDED.status,
        created_at = EXCLUDED.created_at
    RETURNING id INTO v_doc_id;

    -- Delete old chunks for this document to prevent duplicates
    DELETE FROM public.document_chunks WHERE document_id = v_doc_id;

    INSERT INTO public.document_chunks (document_id, chunk_text, embedding)
    VALUES (v_doc_id, p_chunk_text, p_embedding);

    RETURN v_doc_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 4. Enable Row Level Security (RLS)
ALTER TABLE public.raw_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_chunks ENABLE ROW LEVEL SECURITY;

-- 5. Define Access Control Policies

-- Allow full access to service_role (service key)
CREATE POLICY "Allow service_role full access to raw_documents" 
ON public.raw_documents 
TO service_role 
USING (true) 
WITH CHECK (true);

CREATE POLICY "Allow service_role full access to document_chunks" 
ON public.document_chunks 
TO service_role 
USING (true) 
WITH CHECK (true);

-- Allow select access to authenticated users
CREATE POLICY "Allow authenticated users select access to raw_documents" 
ON public.raw_documents 
FOR SELECT 
TO authenticated 
USING (true);

CREATE POLICY "Allow authenticated users select access to document_chunks" 
ON public.document_chunks 
FOR SELECT 
TO authenticated 
USING (true);


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. hybrid_search — called by the LangGraph agent's database_search tool.
--    Runs cosine similarity search on document_chunks, JOINs raw_documents,
--    and applies optional platform / status / author filters.
--    ⚠ Run this in Supabase → SQL Editor before using the /chat/agent endpoint.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.hybrid_search(
    query_embedding  VECTOR(1024),
    platform_filter  TEXT    DEFAULT NULL,
    status_filter    TEXT    DEFAULT NULL,
    author_filter    TEXT    DEFAULT NULL,
    match_count      INT     DEFAULT 5
)
RETURNS TABLE (
    chunk_text  TEXT,
    title       TEXT,
    author      TEXT,
    platform    TEXT,
    status      TEXT,
    created_at  TIMESTAMPTZ,
    similarity  FLOAT,
    body        TEXT,
    external_id TEXT
)
LANGUAGE SQL STABLE AS $$
    SELECT
        dc.chunk_text,
        rd.title,
        rd.author,
        rd.platform,
        rd.status,
        rd.created_at,
        1 - (dc.embedding <=> query_embedding) AS similarity,
        rd.body,
        rd.external_id
    FROM   public.document_chunks dc
    JOIN   public.raw_documents   rd ON rd.id = dc.document_id
    WHERE
        (platform_filter IS NULL OR rd.platform = platform_filter)
        AND (status_filter  IS NULL OR rd.status  = status_filter)
        AND (author_filter  IS NULL OR rd.author  ILIKE '%' || author_filter || '%')
    ORDER BY dc.embedding <=> query_embedding
    LIMIT  match_count;
$$;



-- 7. Chat sessions and messages tables for conversation history persistence.
CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT DEFAULT 'New Chat',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES public.chat_sessions(id) ON DELETE CASCADE NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Enable Row Level Security (RLS) for chat tables
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;

-- Allow full access to service_role (service key)
CREATE POLICY "Allow service_role full access to chat_sessions" 
ON public.chat_sessions 
TO service_role 
USING (true) 
WITH CHECK (true);

CREATE POLICY "Allow service_role full access to chat_messages" 
ON public.chat_messages 
TO service_role 
USING (true) 
WITH CHECK (true);

-- Allow full access to anon
CREATE POLICY "Allow anon full access to chat_sessions" 
ON public.chat_sessions 
TO anon 
USING (true) 
WITH CHECK (true);

CREATE POLICY "Allow anon full access to chat_messages" 
ON public.chat_messages 
TO anon 
USING (true) 
WITH CHECK (true);

-- Allow full access to authenticated users
CREATE POLICY "Allow authenticated users full access to chat_sessions" 
ON public.chat_sessions 
TO authenticated 
USING (true) 
WITH CHECK (true);

CREATE POLICY "Allow authenticated users full access to chat_messages" 
ON public.chat_messages 
TO authenticated 
USING (true) 
WITH CHECK (true);

