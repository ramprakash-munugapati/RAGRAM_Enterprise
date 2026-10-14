# RAGRAM Enterprise – Architecture and Request Flow

This diagram reflects the current implementation in `RagramEnterpriseEngine.py` and `integrations.py`. It distinguishes the implemented core path from the optional FastAPI example and retriever adapters.

```mermaid
flowchart TD
    subgraph Request["A. Core query flow"]
        direction TD
        ClientRequest["1. Caller submits a question"] --> Router["2. QueryRouter cleans the text and derives a basic category filter"]
        Router --> Workflow["3. EnterpriseAgentWorkflow starts an attempt"]
        Workflow --> Embed["4. Create deterministic hash-based query embedding"]
        Embed --> Search["5. PostgresEngine.search filters documents and ranks by Python cosine similarity"]
        Search --> Documents[("SQLAlchemy documents table")]
        Documents --> Results["6. Ranked document rows"]
        Results --> Grade{"7. Heuristic grader finds a query token in context?"}
        Grade -->|Yes| Synthesis["8. Rule-based synthesizer extracts date information and missing fields"]
        Synthesis --> Result["9. Workflow returns answer and missing_info"]
        Result --> ClientResponse["10. Caller receives the workflow result"]
        Grade -->|No| Retry{"Up to 3 retries remain after the initial attempt?"}
        Retry -->|Yes| Rewrite["Append broaden marker to the query"]
        Rewrite --> Router
        Retry -->|No| Fallback["Return empty answer and max-retries message"]
        Fallback --> Result
    end

    subgraph Ingestion["B. Background ingestion"]
        direction LR
        Events[("cdc_events table")] -->|polls| Worker["RealTimeSyncWorker"]
        Worker --> Tick["._tick() extracts title or body and makes a hash embedding"]
        Tick --> Upsert["PostgresEngine.upsert_document"]
        Upsert --> Documents
    end

    subgraph Adapters["C. Optional framework adapters"]
        direction LR
        Engine["PostgresEngine.search"]
        Engine --> LangChain["RagramLangChainRetriever"]
        Engine --> LlamaIndex["RagramLlamaIndexRetriever"]
        LangChain --> LCApp["LangChain application"]
        LlamaIndex --> LIApp["LlamaIndex application"]
    end

    subgraph HttpExample["D. Optional FastAPI example"]
        direction LR
        HttpRequest["POST /query"] --> HttpWorkflow["Calls workflow.run(question)"]
        HttpWorkflow --> Router
        HttpResponse["Answer response model"]
    end

    Config["EnterpriseConfig: database URL, embedding dimension, chunk size, overlap"] --> Search
    Config --> Upsert
    ClientRequest -.-> HttpRequest
    Result -.-> HttpResponse
```

### Legend

- **Numbers 1–10** show the core query lifecycle. The optional HTTP example is shown separately so a response is not drawn back into the request node.
- **Solid arrows** show data or control flow; **dotted arrows** show optional FastAPI entry/response mapping.
- **Cylinder** represents a database table; the decision diamond shows the grader and retry branches.
- The FastAPI block is an example entry point, not a dependency of the core workflow.

### What the current code does

1. A caller invokes the query flow; the optional FastAPI example defines a `POST /query` route.
2. `QueryRouter` uses a local heuristic to clean the question and derive a basic metadata filter. It does not call an LLM.
3. `EnterpriseAgentWorkflow` hashes the routed query into a deterministic pseudo-embedding.
4. `PostgresEngine.search` reads candidate rows, applies metadata filters, and ranks them with Python cosine-similarity calculations.
5. A token-match heuristic grades the returned rows. On a failed grade, the workflow appends `*broaden*` and reruns routing. The loop allows an initial attempt plus up to three retries; on exhaustion, the returned `retries` value is actually the number of attempts.
6. On a passing grade, the built-in synthesizer uses deterministic rules (including date extraction); it is not an LLM. Exhaustion returns an empty answer and a max-retries message with the attempt count.
7. The optional LangChain and LlamaIndex adapters independently call engine search and convert results to their respective formats.

### Implementation notes

- The worker currently polls the `cdc_events` table; a live change stream is not implemented.
- `integrations.py` contains OpenAI, Anthropic, and Ollama backend classes, but the core router and workflow do not call them.
- There is no metrics collector or Prometheus `/metrics` endpoint in the current code.
- The FastAPI example contains a route definition, but its startup wiring has not been verified as runnable. Treat it as an example until its imports and workflow construction are brought in line with the current engine API.

---

*Mermaid diagram; renderable in GitHub Markdown, VS Code, and compatible Markdown editors.*
