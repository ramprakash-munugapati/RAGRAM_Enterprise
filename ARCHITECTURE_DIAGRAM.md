# RAGRAM Enterprise – Architecture Diagram (deep dive)

```mermaid
graph TD
    %% -------------------------------------------------------------
    % 1. Configuration & Initialisation
    %% -------------------------------------------------------------
    subgraph Config ["Configuration"]
        C[EnterpriseConfig] -->|db_url, chunk params| PG[PostgresEngine]
    end

    %% -------------------------------------------------------------
    % 2. Core Engine (SQLite / PostgreSQL + pgvector)
    %% -------------------------------------------------------------
    subgraph Engine ["PostgresEngine"]
        direction TB
        U[upsert_document] -->|text, metadata, embedding| DB[(documents table)]
        S[search] <-- embedding, filters --> DB
    end

    %% -------------------------------------------------------------
    % 3. Real‑time Sync Worker (CDC)
    %% -------------------------------------------------------------
    subgraph Sync ["RealTimeSyncWorker"]
        direction TB
        P["Poll / Stream"] -->|new/updated rows| T[._tick()]
        T -->|extract text + embed| U
        U --> DB
    end

    %% -------------------------------------------------------------
    % 3. Query Routing (LLM‑driven)
    %% -------------------------------------------------------------
    subgraph Routing ["QueryRouter"]
        direction TB
        R[raw user query] -->|structured_output| SQ[StructuredQuery {optimized_query, metadata_filters}]
        SQ -->|post‑processed| S[search query (embedding + filters)]
    end

    %% -------------------------------------------------------------
    % 3. Search & Retrieval
    %% -------------------------------------------------------------
    subgraph Search ["PostgresEngine.search"]
        direction TB
        S -->|cosine similarity| D[documents]
        D -->|top‑k| Rets[Retriever outputs]
    end

    %% -------------------------------------------------------------
    % 4. Retrievers (LangChain / LlamaIndex)
    %% -------------------------------------------------------------
    subgraph Retrievers ["Retrievers"]
        LC[LangChain Retriever] -->|get_relevant_documents| UserApp
        LI[LlamaIndex Retriever] -->|retrieve| UserApp
    end

    %% -------------------------------------------------------------
    % 5. Agentic Workflow (retrieve‑grade‑rewrite)
    %% -------------------------------------------------------------
    subgraph Workflow ["EnterpriseAgentWorkflow"]
        direction TB
        A[retrieve] -->|grade| G[grader (Yes/No)]
        G -- Yes --> S[​synthesize answer] --> A_out[answer]
        G -- No --> R[rewrite query + broaden filters] --> A
        R --> A
        W[max_retries=3] -->|exhausted| F[fallback: "max retries exceeded"]
    end

    %% -------------------------------------------------------------
    % 6. Factual Synthesizer (LLM)
    %% -------------------------------------------------------------
    subgraph Synth ["Synthesis (LLM)"]
        direction TB
        A_out -->|generates answer only from context| Answer[final answer]
        Answer -->|missing_info| MI[missing_info text]
    end

    %% -------------------------------------------------------------
    % 7. API Exposure (FastAPI)
    %% -------------------------------------------------------------
    subgraph API ["FastAPI Service"]
        direction TB
        Endp[POST /query] -->|question| Wkfl[workflow.run]
        Wkfl -->|JSON answer| Resp[Response model]
    end

    %% -------------------------------------------------------------
    % 8. Observability (Prometheus)
    %% -------------------------------------------------------------
    subgraph Metrics ["Prometheus Metrics"]
        direction TB
        MetricsCollector["MetricsCollector"] -->|increment / record| HTTP[/metrics endpoint]
    end

    %% -------------------------------------------------------------
    % 9. Connections between subsystems
    %% -------------------------------------------------------------
    C --> PG
    PG --> Sync
    PG --> Routing
    Routing --> Search
    Search --> Retrievers
    Retrievers --> Workflow
    Workflow --> Synth
    Synth --> API
    API --> Metrics
```

### Legend
- **Boxes** – major subsystems.
- **Arrows** – direction of data / control flow.
- **Sub‑graphs** – group related components for readability.
- **Legend** – explains the symbols used.

### How to read the diagram
1. **Configuration → Engine** supplies the database URL, embedding dimension, and chunk size.
2. **Engine** stores documents (text + vector) and answers similarity searches.
3. **Sync Worker** keeps the vector store up‑to‑date by reading CDC events.
4. **Query Routing** turns a free‑form question into a structured query + filters via an LLM.
5. **Search** converts the optimized query into a vector and pulls the most relevant docs.
6. **Retrievers** expose those docs to LangChain or LlamaIndex agents.
7. **Workflow** orchestrates the retrieve‑grade‑rewrite loop with a hard `max_retries=3` limit.
8. **Synthesis** uses an LLM to produce a factual answer grounded *only* in the validated context; it also reports missing information.
9. **API** exposes the whole flow via a simple POST endpoint; Prometheus metrics can be attached for observability.

--- liên kết (link) về cách các thành phần tương tác với nhau: 
- Cấu hình → Engine → Worker → Routing → Search → Retrievers → Workflow → Synthesizer → API → Metrics.

---
*Diagram generated with Mermaid; renderable in GitHub Markdown, VS Code, and many Markdown editors.*