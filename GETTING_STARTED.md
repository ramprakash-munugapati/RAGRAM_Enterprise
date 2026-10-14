# 🚀 RAGRAM Enterprise – Getting Started

This guide walks you through installing, configuring, and running the **RAGRAM Enterprise** demo.

## 1. Install the dependencies

```bash
# Core dependencies
pip install -r requirements.txt

# Optional extras (choose what you need)
#   LangChain support
pip install langchain-core
#   LlamaIndex support
pip install llama-index-core
#   OpenAI generation
pip install openai
#   Anthropic generation
pip install anthropic
#   FastAPI + uvicorn (for the HTTP service)
pip install fastapi uvicorn
```

## 2. Set up your environment

Create a file named **`.env`** in the project root with the following variables (you can keep the defaults for a SQLite demo):

```env
# --- LLM provider credentials ---
OPENAI_API_KEY=sk-YOUR_OPENAI_KEY          # optional
ANTHROPIC_API_KEY=sk-ant-YOUR_ANTHROPIC_KEY  # optional
OLLAMA_URL=http://localhost:11434          # optional, for local Ollama

# --- Database ---
DB_URL=sqlite:///:memory:          # use a PostgreSQL URL for production

# --- Backend selection ---
# Selects the backend returned by load_backend(); the core CLI workflow
# does not currently call this factory.
# Accepted values: "openai", "anthropic", "ollama"
RAGMA_BACKEND=openai

# --- Chunking parameters (must match the engine defaults) ---
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
```

## 2️⃣  Run the CLI demo

```bash
# If you chose OpenAI
export OPENAI_API_KEY="sk-…"
export RAGMA_BACKEND=openai

# If you chose Anthropic
export ANTHROPIC_API_KEY="sk-ant-…"
export RAGMA_BACKEND=anthropic

# If you chose Ollama (no API key needed)
# Make sure Ollama is running: `ollama serve`
export RAGMA_BACKEND=ollama

# Run the demo query
python cli.py --seed --query "What were the sales figures for the Q3 period and can you tell me about any product launches that happened around the same time?"
```

**Expected output (core demo; the configured LLM backend is not used by this workflow):**

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

If the grader returns **“No”**, the loop appends a `*broaden*` marker to the query and retries (up to three times after the initial attempt). The retry-exhaustion result reports an attempt count; successful results omit the `retries` key.

## 3. Using the LangChain / LlamaIndex retrievers

```python
from integrations import RagramLangChainRetriever, RagramLlamaIndexRetriever
from RagramEnterpriseEngine import PostgresEngine, EnterpriseConfig

engine = PostgresEngine(EnterpriseConfig(db_url="sqlite:///:memory:"))

# LangChain retriever
lc_retriever = RagramLangChainRetriever(engine, top_k=4)
docs = lc_retriever.get_relevant_documents("What were the sales figures for the Q3 period?")

# LlamaIndex retriever
li_retriever = RagramLlamaIndexRetriever(engine, top_k=4)
nodes = li_retriever.retrieve("What were the sales figures for the Q3 period?")
```

## 4. Running with Docker (optional)

```bash
# Build the image
docker build -t rag-entreprise .

# Run the container (replace the API key as needed)
docker run --rm \
  -e OPENAI_API_KEY=sk-… \
  -e RAGMA_BACKEND=openai \
  rag-entreprise
```

## 5. Running the test suite

```bash
pytest test_engine.py -v
```

## 6. CI / CD (optional)

A minimal GitHub Actions workflow is included (`.github/workflows/test.yml`) that runs the pytest suite on every push.

## 7. Need more help?

- **Detailed architecture diagram**: see `ARCHITECTURE_DIAGRAM.md`.
- **Production readiness checklist**: see `PRODUCTION_CHECKLIST.md`.
- **Full API reference**: refer to the FastAPI endpoint `/query` in `examples/fastapi_app.py`.

Enjoy exploring RAGRAM Enterprise! 🎉