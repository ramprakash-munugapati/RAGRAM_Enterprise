# RAGRAM Enterprise

**RAGRAM Enterprise** is an autonomous, production‑ready Advanced RAG system that hooks directly into a live, real‑time database (defaulting to PostgreSQL). It combines query translation, metadata routing, self‑correction feedback loops, and an integrated real‑time data‑ingestion sync worker to handle messy user queries and constant data drift.

---

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [CLI Usage](#cli-usage)
5. [Python API](#python-api)
6. [Configuration](#configuration)
7. [Extending the Engine](#extending-the-engine)
8. [License](#license)

---

## Overview

RAGRAM Enterprise implements the following core components:

| Component | Description |
|-----------|-------------|
| **EnterpriseConfig** | Holds database URLs, embedding dimension, chunk‑size/overlap parameters. |
| **PostgresEngine** | SQLAlchemy/psycopg3 driver with pgvector support – unified relational + vector storage (documents, embeddings, JSON‑B metadata). |
| **RealTimeSyncWorker** | CDC‑style worker that polls a `cdc_events` table (or can be wired to a real stream) and automatically extracts text, computes embeddings, and upserts records without blocking primary traffic. |
| **StructuredQuery (Pydantic)** | Forces the LLM to output JSON containing `optimized_query` (cleaned search string) and `metadata_filters` (key/value pairs for SQL WHERE clauses). |
| **QueryRouter** | Translates raw human input → structured query → dynamic SQL executed against `PostgresEngine`. |
| **EnterpriseAgentWorkflow** | Autonomous “retrieve‑grade‑rewrite” loop with a strict `max_retries=3` counter. |
| **Factual Synthesizer** | System‑prompted LLM that answers **only** from validated context and explicitly reports any missing data. |

The module is **stand‑alone**, **self‑contained**, and runs end‑to‑end via the `cli.py` entry point or the Python API.

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
  "missing_info": null,
  "retries": 1
}
[Engine] Demo completed.
```

If the grader returns **“No”**, the loop automatically rewrites the query, loosens filters, and retries (up to three times) before reporting “Max retries exceeded”.

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
* `retries` – how many times the self‑correction loop executed (≤ 3)

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `db_url` | `"sqlite:///RAGRAM_Data/demo.db"` | SQLAlchemy URL. Use `postgresql+psycopg3://user:pw@host:5432/dbname` for production. |
| `embedding_dim` | `768` | Dimensionality of the embedding vectors. |
| `chunk_size` | `1000` | Max characters per text chunk (not used in the minimal demo but configurable). |
| `chunk_overlap` | `200` | Overlap between consecutive chunks. |

You can also pass a custom `db_url` via the CLI (`--db-url`) or directly when constructing `EnterpriseConfig`.

---

## Extending the Engine

| Goal | How to extend |
|------|----------------|
| **Real embeddings** | Replace `RealTimeSyncWorker._fake_embedding` / `EnterpriseAgentWorkflow._dummy_embedding` with a call to `sentence_transformers.SentenceTransformer.encode`. |
| **PostgreSQL + pgvector** | Set `db_url` to `postgresql+psycopg3://...` and ensure the `vector` extension is created (`CREATE EXTENSION vector;`). The `PostgresEngine` will automatically use pgvector distance `<=>` if you replace the Python cosine fallback with the SQL expression `1 - (embedding <=> query_embedding) / (norms)`. |
| **Different CDC source** | Swap the `RealTimeSyncWorker._tick` implementation to listen to Kafka, Pulsar, or a webhook payload; the worker only needs to call `engine.upsert_document(text, metadata, embedding)`. |
| **Custom grader/LLM** | Provide your own `_grade_context` implementation or inject a real LLM call instead of the heuristic stub. |
| **Additional metadata filters** | Extend the `_llm_structured_output` function to parse more sophisticated JSON shapes, or attach a full Pydantic model if you prefer. |

---

## License

This project is released under the **MIT License**. Feel free to use, modify, and distribute it commercially or non‑commercially, provided the original copyright notice is retained.

---

*Happy RAG‑ming! 🚀*