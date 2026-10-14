# RAGRAM Enterprise

**RAGRAM Enterprise** is a demo/reference Advanced RAG engine built around SQLAlchemy storage, a CDC-table polling example, and a heuristic retrieve-grade-rewrite workflow. The current core uses deterministic pseudo-embeddings and rule-based synthesis; the optional LLM backends, HTTP example, and retriever adapters are separate integrations rather than a production-ready end-to-end deployment.

---
## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [CLI Usage](#cli-usage)
5. [Python API](#python-api)
6. [Architecture](#architecture)
7. [Integration Guidelines](#integration-guidelines)
8. [Configuration](#configuration)
9. [Extending the Engine](#extending-the-engine)
10. [License](#license)

---
## Overview

RAGRAM Enterprise implements the following core components:

| Component | Description |
|-----------|-------------|
| **EnterpriseConfig** | Holds database URLs, embedding dimension, chunk‑size/overlap parameters. |
| **PostgresEngine** | SQLAlchemy document storage and metadata filtering, with query results ranked using Python cosine-similarity calculations. |
| **RealTimeSyncWorker** | Demo worker that polls a `cdc_events` table, extracts a title or body, creates a deterministic hash-based pseudo-embedding, and upserts a document. |
| **StructuredQuery** | Lightweight Python object holding an optimized query and metadata filters; it is not a Pydantic model and is currently populated by a local heuristic. |
| **QueryRouter** | Cleans the raw query and derives a basic metadata filter using local heuristics; it does not call an LLM or generate SQL. |
| **EnterpriseAgentWorkflow** | Heuristic retrieve-grade-rewrite loop with an initial attempt and up to three retries. |
| **Factual Synthesizer** | Deterministic rule-based summary and missing-information reporting; the core workflow does not currently call an LLM. |

The engine can be invoked through `cli.py` or the Python API. See the implementation notes in the architecture section before relying on the optional integrations or HTTP example.

---
## Architecture

See the [numbered architecture and request-flow diagram](./ARCHITECTURE_DIAGRAM.md) for the current implementation, including background ingestion, optional retriever adapters, retry behavior, and implementation limitations.

### Key flows

1. **Ingestion** – `RealTimeSyncWorker` polls `cdc_events`, extracts a title or body, makes a deterministic hash embedding, and upserts the document.
2. **Query routing** – `QueryRouter` uses a local heuristic to clean the query and derive a basic metadata filter; it does not call the generation backends.
3. **Search** – `PostgresEngine.search` applies metadata filters and ranks stored embeddings with Python cosine-similarity calculations.
4. **Grading and retry** – The workflow uses a token-match heuristic. A failed grade appends `*broaden*` to the query and repeats routing; the loop allows an initial attempt plus up to three retries.
5. **Synthesis** – The core workflow uses deterministic rules to extract date information and report missing fields; it does not call an LLM backend.
6. **Retriever adapters** – The optional LangChain and LlamaIndex wrappers independently call engine search and convert returned documents to their respective formats.
7. **HTTP example** – `examples/fastapi_app.py` contains a `POST /query` route, but its startup wiring has not been verified as runnable against the current workflow API.

The OpenAI, Anthropic, and Ollama backend classes in `integrations.py` are available separately, but are not connected to the core router or workflow. The repository does not currently implement a Prometheus metrics endpoint.

---
## Installation

```bash
# 1️⃣  Clone the repository (or copy the files)
git clone https://github.com/your‑org/RAGRAM_Enterprise.git
cd RAGRAM_Enterprise

# 2️⃣  Install the required dependencies
pip install -r requirements.txt
```

`requirements.txt` contents:

```
pydantic>=2.5
sqlalchemy>=2.0
psycopg[binary]>=3          # optional – only needed for a real PostgreSQL server
sentence-transformers>=2.2  # optional – for real embeddings
```

> **Optional extras** (install only what you need):
* `langchain-core` – for the LangChain retriever.
* `llama-index-core` – for the LlamaIndex retriever.
* `openai` – for OpenAI generation backend.
* `anthropic` – for Anthropic generation backend.
* `fastapi` & `uvicorn` – for the FastAPI demo service.

---
## Quick Start (demo mode – SQLite)

```bash
python cli.py --seed --query "What were the sales figures for the Q3 period and can you tell me about any product launches that happened around the same time?"
```

* `--seed` creates a mock `cdc_events` table with sample rows.
* `--query` supplies the user question; if omitted a default ambiguous query is used.

You should see output similar to:

```
=== User Query ===
What were the sales figures for the Q3 period and can you tell me
about any product launches that happened around the same time? Also,
did the board approve any budget changes in 2024?

--- Running EnterpriseAgentWorkflow ---

[Workflow] Attempt 1/3
[Workflow] Grader said 'Yes' (attempt 1).

=== Final Result ===
{
  "answer": "The records concern the date 2024-09-01.",
  "missing_info": null
}
[Engine] Demo completed.
```

If the grader returns **“No”**, the loop appends a `*broaden*` marker to the query and retries (up to three times after the initial attempt) before reporting “Max retries exceeded”.

---
## CLI Usage

```bash
python cli.py [OPTIONS]

Options:
  --db-url TEXT        SQLAlchemy database URL (default: sqlite:///RAGRAM_Data/demo.db)
  --seed               Populate a mock cdc_events table (useful for demo)
  --query TEXT         User query to run through the workflow (default: built‑in ambiguous query)
  --help               Show this message and exit
```

### Examples

```bash
# Run with a custom query
python cli.py --query "Summarize the Q3 budget changes and any product launches"

# Connect to a real PostgreSQL instance
python cli.py --db-url "postgresql+psycopg3://user:pw@host:5432/mydb" --seed
```
---
## Python API

```python
from RagramEnterpriseEngine import (
    EnterpriseConfig,
    PostgresEngine,
    RealTimeSyncWorker,
    QueryRouter,
    EnterpriseAgentWorkflow,
)

# 1️⃣  Configure the engine
cfg = EnterpriseConfig(db_url="sqlite:///:memory:")       # or a real PostgreSQL URL
engine = PostgresEngine(cfg)

# 2️⃣  (Optional) seed CDC events for the sync worker
with engine._engine.begin() as conn:
    # ... add CdcEvent rows as shown in the source ...

# 3️⃣  Start the sync worker in a background thread
worker = RealTimeSyncWorker(engine, poll_interval=0.5)
t = threading.Thread(target=worker.start, daemon=True)
t.start()

# 4️⃣  Build the router and workflow
router = QueryRouter(engine)
workflow = EnterpriseAgentWorkflow(engine, router, top_k=3)

# 5️⃣  Run a user query
result = workflow.run(
    "What were the sales figures for the Q3 period and any product launches around the same time?"
)
print(json.dumps(result, indent=2))
```

The `run` method returns a dict with keys:

* `answer` – the synthesized factual answer (or empty string if failed)
* `missing_info` – `None` if the answer is complete, otherwise a semicolon‑separated list of missing pieces
* `retries` – on retry exhaustion, the workflow currently reports the number of attempts (initial attempt plus up to three retries); successful results omit this key.

---
## Architecture (detail)

See the [numbered architecture and request-flow diagram](./ARCHITECTURE_DIAGRAM.md). It documents the implemented core path and distinguishes it from optional adapters and examples.

The current core flow uses heuristic routing and grading, hash-based pseudo-embeddings, Python cosine-similarity ranking, and deterministic answer summarization. The LLM backend classes in `integrations.py` are not wired into this workflow.

---
## Integration Guidelines

| Goal | How to enable |
|------|---------------|
| **LangChain retriever** | `from integrations import RagramLangChainRetriever; retriever = RagramLangChainRetriever(engine)` – used as any `langchain_core.retrievers.BaseRetriever`. |
| **LlamaIndex retriever** | `from integrations import RagramLlamaIndexRetriever; retriever = RagramLlamaIndexRetriever(engine)` – returns `NodeWithScore` objects. |
| **OpenAI generation** | `OpenAIGeneration` is available in `integrations.py`; setting its API key does not connect it to the core query workflow. |
| **Anthropic generation** | `AnthropicGeneration` is available in `integrations.py`; it is not currently invoked by the core workflow. |
| **Ollama local LLM** | `OllamaGeneration` is available in `integrations.py`; setting `RAGMA_BACKEND` alone does not connect it to the core workflow. |
| **FastAPI example** | `examples/fastapi_app.py` defines `POST /query`, but its startup wiring is not compatible with the current workflow constructor and has not been verified as runnable. |
| **Custom LLM backend** | Implement `GenerationBackend` and register it in `load_backend()`; the current `EnterpriseAgentWorkflow` does not accept a backend instance. |

---
## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `db_url` | `"sqlite:///RAGRAM_Data/demo.db"` | SQLAlchemy URL. Use `postgresql+psycopg3://user:pw@host:5432/dbname` for production. |
| `embedding_dim` | `768` | Dimensionality of the embedding vectors. |
| `chunk_size` | `1000` | Max characters per text chunk. |
| `chunk_overlap` | `200` | Overlap between consecutive chunks. |

You can also pass a custom `db_url` via the CLI (`--db-url`) or directly when constructing `EnterpriseConfig`.

---
## License

This project is released under the **MIT License**. Feel free to use, modify, and distribute it commercially or non‑commercially, provided the original copyright notice is retained.

---
*Happy RAG‑ming! 🚀*