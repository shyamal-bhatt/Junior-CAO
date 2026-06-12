# Junior CAO

### About
Junior CAO is a high-performance, feature-focused Assistant Chat Overlay application designed to serve as an intelligent context-aware copilot. By integrating communication platforms and repositories with a retrieval-augmented generation (RAG) framework, it retrieves, normalizes, embeds, and queries workspace context to assist users with grounded conversations.

---

### Third-Party APIs Consumed
- **Nango API**: Facilitates secure OAuth connection establishment and unified webhook-driven synchronization across platforms.
- **OpenRouter API**: Manages large language model inferences (specifically leveraging `openai/gpt-4o-mini` by default) for user query intent classification and response synthesis.
- **GitHub API**: Ingests issue events, pull requests, and commit logs (synced via Nango).
- **Google Workspace APIs (Gmail & Google Calendar)**: Synchronizes emails, message attachments (PDF, Excel parsed text), and calendar events (synced via Nango).
- **Supabase**: Serves as the cloud database and vector store, utilizing `pgvector` for storing and performing hybrid searches.

---

### Connected Data Sources
The RAG pipeline ingests and synchronizes context from the following workspace sources:
- **GitHub**: Code repositories, issue trackers, pull requests, and commit logs.
- **Gmail**: Inbound and outbound emails, thread context, and parsed file attachments (PDFs and Excel spreadsheets).
- **Google Calendar**: Planned meetings, schedule details, participants, and event descriptions.

---

### System Architecture & Data Flow

#### 1. Nango to Supabase Data Flow (Ingestion & Normalization)
This diagram illustrates how data is ingested from external third-party sources (GitHub, Gmail, Google Calendar) via Nango webhooks, normalized, chunked, embedded, and saved transactionally to Supabase.

```mermaid
graph TD
    %% Source Platforms
    subgraph Third-Party Sources
        GH[GitHub Events]
        GM[Gmail / Attachments]
        GC[Google Calendar Events]
    end

    %% Sync Layer
    subgraph Nango Sync Engine
        NangoSync[Nango Webhook Handler]
    end

    %% Backend Normalization
    subgraph Backend Services
        Validate[Attachment Validator & Router]
        ParseExcel[Excel Parser openpyxl]
        ParsePDF[PDF Parser PyPDF2]
        Chunking[Text Chunking split_text]
        EmbedService[Embedding Service]
        LocalModel[BAAI/bge-large-en-v1.5 <br> 1024-dim Local Model]
    end

    %% Database Layer
    subgraph Supabase Storage
        RawDocs[(raw_documents Table)]
        DocChunks[(document_chunks Table)]
    end

    %% Connections
    GH --> NangoSync
    GM --> NangoSync
    GC --> NangoSync
    
    NangoSync -->|Webhook Payload| Validate
    Validate -->|.xlsx / .xls| ParseExcel
    Validate -->|.pdf| ParsePDF
    Validate -->|Plain Text| Chunking
    
    ParseExcel --> Chunking
    ParsePDF --> Chunking
    
    Chunking -->|Text Chunks| EmbedService
    EmbedService -->|Generate Embedding| LocalModel
    LocalModel -->|1024-dim Vector| EmbedService
    
    EmbedService -->|Transactional Insert/Upsert| RawDocs
    EmbedService -->|Vector Store Insert| DocChunks
```

---

#### 2. Context Engine (Retrieval & Grounding)
This diagram outlines how context is searched using a hybrid approach (Dense Vector Embedding Search + Sparse Full-Text Search) combined via Reciprocal Rank Fusion (RRF), and how retrieval results are used to ground the LLM's responses.

```mermaid
graph TD
    %% User Query & Embedding
    User[User Query] --> IntentRouter{Intent Router}
    
    subgraph Context Engine Retrieval
        QueryEmbed[Generate Query Embedding <br> BAAI/bge-large-en-v1.5]
        QueryFTS[Extract Plain Text Query]
        
        subgraph Hybrid Search RRF
            Dense[Dense Search: Cosine Similarity <br> HNSW Index on document_chunks]
            Sparse[Sparse Search: Full-Text Search <br> GIN Index on raw_documents]
            RRF[Reciprocal Rank Fusion Aggregator <br> 1.0 / 60 + Rank]
        end
    end

    subgraph Grounded Synthesis
        Prompt[System Prompt with Grounded Context]
        LLM[OpenRouter API <br> openai/gpt-4o-mini]
    end

    %% Flow connections
    IntentRouter -->|Requires Context| QueryEmbed
    IntentRouter -->|Requires Context| QueryFTS
    
    QueryEmbed --> Dense
    QueryFTS --> Sparse
    
    Dense --> RRF
    Sparse --> RRF
    
    RRF -->|Ranked Document Chunks| Prompt
    Prompt --> LLM
    LLM -->|Grounded Response| User
```

---

#### 3. Orchestration Workflow (LangGraph Agentic Loop)
This diagram details the core orchestration flow of the agent. The agent determines user intent, conditionally calls tools (like `database_search`), validates context grounding, and outputs the final response.

```mermaid
graph TD
    Start([Receive User Message]) --> AgentNode[Agent Core / LangGraph Controller]
    
    AgentNode --> Router{Intent Router / Tool Call?}
    
    Router -->|Database Search Tool| DBSearch[Database Search Tool]
    Router -->|Direct Conversation| DirectReply[Generate Chat Response]
    
    DBSearch --> EmbedQuery[Embed & Query Supabase RRF]
    EmbedQuery --> ContextFetch[Retrieve & Format Context]
    ContextFetch --> AgentNode
    
    DirectReply --> Synthesize[Synthesize Grounded Response]
    Synthesize --> Output([Send Chat Message to UI])
```
