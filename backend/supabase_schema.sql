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
    is_mock BOOLEAN DEFAULT FALSE, -- Tag to identify seeded/mock data
    created_at TIMESTAMP WITH TIME ZONE,
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Ensure the column exists on existing installations
ALTER TABLE public.raw_documents ADD COLUMN IF NOT EXISTS is_mock BOOLEAN DEFAULT FALSE;

-- Index for querying documents by platform and project tags
CREATE INDEX IF NOT EXISTS idx_raw_documents_platform_project_tag 
ON public.raw_documents (platform, project_tag);

-- Index for full-text search on title and body
CREATE INDEX IF NOT EXISTS idx_raw_documents_fts 
ON public.raw_documents USING gin (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, '')));


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
-- Drop old overloaded signatures first to prevent candidats ambiguity errors.
DROP FUNCTION IF EXISTS public.insert_document_with_chunks(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITH TIME ZONE, TEXT, VECTOR);
DROP FUNCTION IF EXISTS public.insert_document_with_chunks(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITH TIME ZONE, TEXT, public.vector);
DROP FUNCTION IF EXISTS public.insert_document_with_chunks(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMP WITH TIME ZONE, TEXT, public.vector, BOOLEAN);

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
    p_embedding VECTOR(1024),
    p_is_mock BOOLEAN DEFAULT FALSE
) RETURNS UUID AS $$
DECLARE
    v_doc_id UUID;
BEGIN
    INSERT INTO public.raw_documents (external_id, title, body, author, status, platform, project_tag, created_at, is_mock)
    VALUES (p_external_id, p_title, p_body, p_author, p_status, p_platform, p_project_tag, p_created_at, p_is_mock)
    ON CONFLICT (external_id) 
    DO UPDATE SET 
        title = EXCLUDED.title,
        body = EXCLUDED.body,
        status = EXCLUDED.status,
        created_at = EXCLUDED.created_at,
        is_mock = EXCLUDED.is_mock
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

-- Allow full access to authenticated users
DROP POLICY IF EXISTS "Allow authenticated users select access to raw_documents" ON public.raw_documents;
CREATE POLICY "Allow authenticated users full access to raw_documents" 
ON public.raw_documents 
TO authenticated 
USING (true) 
WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users select access to document_chunks" ON public.document_chunks;
CREATE POLICY "Allow authenticated users full access to document_chunks" 
ON public.document_chunks 
TO authenticated 
USING (true) 
WITH CHECK (true);

-- Allow full access to anon users
CREATE POLICY "Allow anon users full access to raw_documents" 
ON public.raw_documents 
TO anon 
USING (true) 
WITH CHECK (true);

CREATE POLICY "Allow anon users full access to document_chunks" 
ON public.document_chunks 
TO anon 
USING (true) 
WITH CHECK (true);


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. hybrid_search — called by the LangGraph agent's database_search tool.
--    Runs cosine similarity search or date-based search on document_chunks,
--    JOINs raw_documents, and applies optional platform / status / author / project filters.
--    Supports sort_by: 'similarity' or 'date'.
-- ─────────────────────────────────────────────────────────────────────────────
-- Drop old overloaded signatures first to prevent candidates ambiguity errors.
DROP FUNCTION IF EXISTS public.hybrid_search(VECTOR, TEXT, TEXT, TEXT, TEXT, TEXT, INT);
DROP FUNCTION IF EXISTS public.hybrid_search(public.vector, TEXT, TEXT, TEXT, TEXT, TEXT, INT);
DROP FUNCTION IF EXISTS public.hybrid_search(VECTOR, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INT);
DROP FUNCTION IF EXISTS public.hybrid_search(public.vector, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INT);

CREATE OR REPLACE FUNCTION public.hybrid_search(
    query_embedding    VECTOR(1024),
    query_text         TEXT,
    platform_filter    TEXT    DEFAULT NULL,
    status_filter      TEXT    DEFAULT NULL,
    author_filter      TEXT    DEFAULT NULL,
    project_tag_filter TEXT    DEFAULT NULL,
    sort_by            TEXT    DEFAULT 'similarity',
    match_count        INT     DEFAULT 5
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
    external_id TEXT,
    project_tag TEXT,
    is_mock     BOOLEAN
)
LANGUAGE plpgsql SECURITY DEFINER STABLE AS $$
BEGIN
    IF sort_by = 'date' THEN
        RETURN QUERY
        SELECT
            dc.chunk_text,
            rd.title,
            rd.author,
            rd.platform,
            rd.status,
            rd.created_at,
            1.0 - (dc.embedding <=> query_embedding) AS similarity,
            rd.body,
            rd.external_id,
            rd.project_tag,
            rd.is_mock
        FROM   public.document_chunks dc
        JOIN   public.raw_documents   rd ON rd.id = dc.document_id
        WHERE
            (platform_filter IS NULL OR rd.platform = platform_filter)
            AND (status_filter  IS NULL OR rd.status  = status_filter)
            AND (author_filter  IS NULL OR rd.author  ILIKE '%' || author_filter || '%')
            AND (project_tag_filter IS NULL OR rd.project_tag = project_tag_filter)
        ORDER BY rd.created_at DESC NULLS LAST
        LIMIT  match_count;
    ELSE
        -- RRF Hybrid Search
        RETURN QUERY
        WITH vector_search AS (
            SELECT
                dc.id AS chunk_id,
                ROW_NUMBER() OVER (ORDER BY dc.embedding <=> query_embedding) AS rank
            FROM public.document_chunks dc
            JOIN public.raw_documents rd ON rd.id = dc.document_id
            WHERE
                (platform_filter IS NULL OR rd.platform = platform_filter)
                AND (status_filter  IS NULL OR rd.status  = status_filter)
                AND (author_filter  IS NULL OR rd.author  ILIKE '%' || author_filter || '%')
                AND (project_tag_filter IS NULL OR rd.project_tag = project_tag_filter)
        ),
        text_search AS (
            SELECT
                dc.id AS chunk_id,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank(
                        to_tsvector('english', coalesce(rd.title, '') || ' ' || coalesce(rd.body, '')),
                        websearch_to_tsquery('english', query_text)
                    ) DESC
                ) AS rank
            FROM public.document_chunks dc
            JOIN public.raw_documents rd ON rd.id = dc.document_id
            WHERE
                to_tsvector('english', coalesce(rd.title, '') || ' ' || coalesce(rd.body, '')) @@ websearch_to_tsquery('english', query_text)
                AND (platform_filter IS NULL OR rd.platform = platform_filter)
                AND (status_filter  IS NULL OR rd.status  = status_filter)
                AND (author_filter  IS NULL OR rd.author  ILIKE '%' || author_filter || '%')
                AND (project_tag_filter IS NULL OR rd.project_tag = project_tag_filter)
        )
        SELECT
            dc.chunk_text,
            rd.title,
            rd.author,
            rd.platform,
            rd.status,
            rd.created_at,
            1.0 - (dc.embedding <=> query_embedding) AS similarity,
            rd.body,
            rd.external_id,
            rd.project_tag,
            rd.is_mock
        FROM public.document_chunks dc
        JOIN public.raw_documents rd ON rd.id = dc.document_id
        LEFT JOIN vector_search vs ON vs.chunk_id = dc.id
        LEFT JOIN text_search ts ON ts.chunk_id = dc.id
        WHERE
            vs.rank IS NOT NULL OR ts.rank IS NOT NULL
        ORDER BY
            coalesce(1.0 / (60.0 + vs.rank), 0.0) + coalesce(1.0 / (60.0 + ts.rank), 0.0) DESC
        LIMIT match_count;
    END IF;
END;
$$;


-- Helper function to clear all raw documents and chunks for cleanup.
CREATE OR REPLACE FUNCTION public.clear_all_documents()
RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
    DELETE FROM public.raw_documents WHERE id IS NOT NULL;
END;
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

