# 📋 RAGRAM Enterprise – Production Readiness Checklist

## 1️⃣  Core Engine
- [ ] **EnterpriseConfig** reads `DB_URL`, `embedding_dim`, `chunk_size`, `chunk_overlap` from environment or `.env`.
- [ ] `PostgresEngine` creates `documents` + `cdc_events` tables on startup.
- [ ] **pgvector** extension enabled on PostgreSQL (`CREATE EXTENSION vector;`).
- [ ] **Connection pooling** configured (`pool_size`, `max_overflow`) for production traffic.

## 2️⃣  Embeddings
- [ ] **Real embeddings** replace the hash‑based `_fake_embedding`:
  - `sentence‑transformers.All‑MiniLM‑L6‑v2` (384‑dim) or
  - OpenAI `text‑embedding‑3‑small` (1536‑dim) via `OpenAIEmbeddings`.
- [ ] Embedding function passed to `PostgresEngine(embedding_fn=…)`.

## 3️⃣  LLM Back‑ends
| Backend | Env var | Required package |
|---------|---------|-----------------|
| OpenAI | `OPENAI_API_KEY` + `RAGMA_BACKEND=openai` | `openai` |
| Anthropic | `ANTHROPIC_API_KEY` + `RAGMA_BACKEND=anthropic` | `anthropic` |
| Ollama (stdlib) | `OLLAMA_URL` (default `http://localhost:11434`) | *no extra pip* |

- [ ] `load_backend()` in `integrations.py` returns the correct subclass.
- [ ] **Structured output** prompt tuned so the model always returns `{"optimized_query": "...", "metadata_filters": {...}}`.
- [ ] **Grader** prompt tuned for Yes/No decisions.
- [ ] **Synthesizer** prompt forces answer‑only‑from‑context and reports missing info.

## 4️⃣  Retrievers
| Retriever | Package | Key method |
|-----------|---------|------------|
| `RagramLangChainRetriever` | `langchain-core` | `get_relevant_documents(query)` → `List[Document]` |
| `RagramLlamaIndexRetriever` | `llama-index-core` | `retrieve(query)` → `List[NodeWithScore]` |

- [ ] Both wrappers use the engine’s `search` method with a (real or pseudo) embedding.
- [ ] Tests verify that the retrievers return the expected number of documents.

## 5️⃣  Self‑Correction Loop
- [ ] `EnterpriseAgentWorkflow.max_retries = 3` is enforced.
- [ ] Each retry increments a **token‑budget counter** (optional) and logs the reason.
- [ ] If retries exhaust, the workflow returns `{"answer":"", "missing_info":"Max retries exceeded", "retries":3}`.

## 6️⃣  Real‑Time Sync Worker
- [ ] `RealTimeSyncWorker` polls a `cdc_events` table (or a Kafka/Pulsar topic) at `poll_interval`.
- [ ] Worker **does not block** primary application traffic (run in a daemon thread or separate process).
- [ ] **Persisted cursor** (`processed_events` table) so the worker survives restarts.
- [ ] **Graceful shutdown** on `KeyboardInterrupt`.

## 7️⃣  FastAPI Service
- [ ] `examples/fastapi_app.py` runs with `uvicorn`.
- [ ] Endpoint `POST /query` accepts `{ "question": "..." }` and returns:
  ```json
  { "answer": "...", "missing_info": "...", "retries": N }
  ```
- [ ] **Authentication** (optional): `HTTPBearer` with `API_KEY` from env.
- [ ] **Health check** endpoint `GET /health` returns `{"status":"ok"}`.

## 8️⃣  Observability (Prometheus)
- [ ] `MetricsCollector` (from `prometheus_metrics.py`) exposed at `/metrics`.
- [ ] Metrics:
  - `ragram_requests_total` (counter, labels: `request_id`)
  - `ragram_request_latency_seconds` (histogram, labels: `request_id`)
  - `ragram_retries_total` (counter, labels: `request_id`)
- [ ] Docker image exposes port `8000` for the metrics endpoint.

## 9️⃣  Security & Deployment
- [ ] **Secret management**: all secrets (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DB_URL`) stored in `.env`; never committed to version control.
- [ ] **Dockerfile** builds a minimal image (see `Dockerfile` in the repo).
- [ ] **Health checks** and **liveness** probes for Kubernetes deployments.
- [ ] **Rate‑limit** on LLM calls (e.g., using `tenacity` or provider‑side quotas).

## 10️⃣  Monitoring & Alerting
- [ ] Prometheus scrapes `/metrics` every 30 seconds.
- [ ] Alerts if:
  - `ragram_requests_total` spikes > 2× baseline.
  - `ragram_retries_total` > 5 per hour.
  - Latency > 5 seconds for > 10 % of requests.

## 11️⃣  Documentation
- [ ] `GETTING_STARTED.md` – step‑by‑step for new users.
- [ ] `ARCHITECTURE_DIAGRAM.md` – visual overview of components.
- [ ] `PRODUCTION_CHECKLIST.md` – this file.
- [ ] API specification (Open/JSON Schema) generated from the FastAPI model.

---
*Keep this checklist updated as the project evolves.  Tick each item before moving the project to production.*