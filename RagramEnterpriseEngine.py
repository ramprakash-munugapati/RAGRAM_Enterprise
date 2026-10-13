from __future__ import annotations

import os
import json
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import sqlalchemy as sa

# ------------------------------------------------------------------
# Load optional .env file (does nothing if python‑dotenv is not installed)
# ------------------------------------------------------------------
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()                  # reads .env in the current working directory
except Exception:                  # pragma: no cover
    pass                           # continue without .env – env vars may already exist
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    JSON,
    text,
)
from sqlalchemy.orm import Session, declarative_base, registry

# Ensure the SQLite file can be created
os.makedirs("C:/RAGRAM_Enterprise", exist_ok=True)


# ----------------------------------------------------------------------
# 1️⃣  Configuration
# ----------------------------------------------------------------------


class EnterpriseConfig:
    """Holds all tunable parameters for the engine.

    Parameters
    ----------
    db_url : str
        SQLAlchemy‑compatible database URL (e.g. ``postgresql+psycopg3://...``).
        Falls back to a file‑based SQLite database when omitted (useful for demo).
    embedding_dim : int
        Dimensionality of the embeddings produced by the embedding model.
    chunk_size : int
        Maximum characters per text chunk when ingesting documents.
    chunk_overlap : int
        Overlap between consecutive chunks.
    """

    def __init__(
        self,
        *,
        db_url: Optional[str] = None,
        embedding_dim: int = 768,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> None:
        self.db_url = db_url or "sqlite:///C:/RAGRAM_Enterprise/demo.db"
        self.embedding_dim = embedding_dim
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap


# ----------------------------------------------------------------------
# 2️⃣  Unified relational + vector storage (pgvector‑ready)
# ----------------------------------------------------------------------


Base = declarative_base()


class CdcEvent(Base):
    """Simplified CDC event model used by the sync worker."""

    __tablename__ = "cdc_events"

    id = Column(Integer, primary_key=True)
    operation = Column(String)
    payload = Column(JSON)


class Document(Base):
    """ORM mapping to the ``documents`` table.

    Stores raw text, a numeric embedding vector (pgvector), and an arbitrary
    metadata JSONB dict.
    """

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    text = Column(String, nullable=False)
    embedding = sa.ARRAY(Float)
    doc_meta = Column(JSON, nullable=True, default={})
    created_at = Column(DateTime, default=sa.func.now())


class PostgresEngine:
    """Unified relational + vector storage driver.

    Wraps SQLAlchemy + pgvector syntax. All methods are thread‑safe when used
    with a scoped session; the demo uses a simple ``Session``.
    """

    def __init__(self, config: EnterpriseConfig) -> None:
        self.config = config
        self._engine = create_engine(
                config.db_url, future=True, echo=False, connect_args={"check_same_thread": False}
            )
        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def upsert_document(
        self,
        *,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
    ) -> Document:
        """Insert or update a document (idempotent by primary key)."""
        stmt = (
            sa.insert(Document)
            .values(
                id=uuid.uuid4().int & (1 << 31),
                text=text,
                meta=metadata or {},
                embedding=embedding,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={"text": text, "meta": metadata or {}, "embedding": embedding},
            )
        )
        with Session(self._engine) as session:
            session.execute(stmt)
            session.commit()
            row = session.query(Document).get(statement.lastrowid)  # type: ignore
            return row  # type: ignore

    # ------------------------------------------------------------------
    # Vector similarity search (cosine)
    # ------------------------------------------------------------------

    def search(
        self,
        query_embedding: List[float],
        *,
        metadata_filters: Optional[Dict[str, Any]] = None,
        limit: int = 4,
    ) -> List[Document]:
        """Return the *limit* most similar documents to the embedding.

        When pgvector is available the query uses ``<=`` distance; otherwise
        a Python‑based cosine approximation is applied.
        """
        with Session(self._engine) as session:
            q = session.query(Document)

            if metadata_filters:
                for k, v in metadata_filters.items():
                    q = q.filter(Document.doc_meta.contains({k: v}))

            candidates = q.all()

            if not query_embedding:
                return []

            q_norm = sum(x * x for x in query_embedding) ** 0.5
            results: List[Tuple[Document, float]] = []
            for doc in candidates:
                if not doc.embedding:
                    continue
                doc_norm = sum(x * x for x in doc.embedding) ** 0.5
                if doc_norm == 0 or q_norm == 0:
                    sim = 0.0
                else:
                    dot = sum(a * b for a, b in zip(query_embedding, doc.embedding))
                    sim = dot / (q_norm * doc_norm)
                results.append((doc, sim))

            results.sort(key=lambda r: r[1], reverse=True)
            return [doc for doc, _ in results[:limit]]


# ----------------------------------------------------------------------
# 3️⃣  Real‑Time Sync Pipeline (CDC‑style worker)
# ----------------------------------------------------------------------


class RealTimeSyncWorker:
    """Monitors a database for change‑data‑capture events and keeps the
    vector store in sync.

    In production this would connect to a logical replication slot or listen
    to a webhook.  The demo polls a ``cdc_events`` table.
    """

    def __init__(self, engine: PostgresEngine, poll_interval: float = 1.0) -> None:
        self.engine = engine
        self.poll_interval = poll_interval
        self._processed: set = set()

    def start(self) -> None:
        """Run an infinite polling loop (blocking).  Meant to be executed in a
        separate thread or async task."""
        try:
            while True:
                self._tick()
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            pass

    def _tick(self) -> None:
        """Fetch new CDC rows and upsert them into the vector store."""
        with Session(self.engine._engine) as session:
            try:
                rows = session.query(CdcEvent).all()
            except sa.exc.NoSuchTableError:
                return

            for row in rows:
                event_id, operation, payload = row.id, row.operation, row.payload
                if event_id in self._processed:
                    continue
                self._processed.add(event_id)

                text = payload.get("title") or payload.get("body") or ""
                meta = {k: v for k, v in payload.items() if k not in ("title", "body")}

                embedding = self._fake_embedding(text)

                self.engine.upsert_document(
                    text=text,
                    metadata=meta,
                    embedding=embedding,
                )

    @staticmethod
    def _fake_embedding(text: str, dim: Optional[int] = None) -> List[float]:
        """Deterministic pseudo‑embedding produced from *text* (hash‑based)."""
        import hashlib

        d = dim or 768
        h = hashlib.sha256(text.encode()).digest()
        return [(b / 255.0) * 2.0 - 1.0 for b in h[:dim]]


# ----------------------------------------------------------------------
# 4️⃣  Agentic Query Rewriter & Router (structured LLM output)
# ----------------------------------------------------------------------


class StructuredQuery:
    """Pydantic‑style schema forcing the LLM to return a deterministic JSON
    object containing ``optimized_query`` and ``metadata_filters``.

    The schema is enforced by the caller; no pydantic dependency is required
    for the demo – the stub implementation simply respects the field names.
    """

    def __init__(self, optimized_query: str, metadata_filters: Dict[str, Any]) -> None:
        self.optimized_query = optimized_query
        self.metadata_filters = metadata_filters


def _llm_structured_output(raw_prompt: str) -> StructuredQuery:
    """Very small stub that pretends to call an LLM and returns a dummy
    ``StructuredQuery``.  Replace with a real LLM API call."""
    filler = r"\b(?:can you|could you|please|would you|i would like|i m looking for)\b"
    cleaned = re.sub(filler, "", raw_prompt, flags=re.IGNORECASE).strip()

    filters: Dict[str, Any] = {}
    for token in re.findall(r"[A-Za-z0-9]+", cleaned):
        if token[0].isupper() and len(token) > 3:
            filters.setdefault("category", token.lower())

    return StructuredQuery(
        optimized_query=cleaned,
        metadata_filters=filters or {"category": "unspecified"},
    )


class QueryRouter:
    """Translates raw human language into a concrete SQL‑friendly query + filters."""

    def __init__(self, engine: PostgresEngine) -> None:
        self.engine = engine

    def route(self, raw_user_query: str) -> Tuple[str, Dict[str, Any]]:
        """Return ``(optimized_query, metadata_filters)`` derived from the
        user's free‑form input."""
        structured = _llm_structured_output(raw_user_query)
        return structured.optimized_query, structured.metadata_filters


# ----------------------------------------------------------------------
# 5️⃣  Self‑Correction Verification Loop (EnterpriseAgentWorkflow)
# ----------------------------------------------------------------------


class EnterpriseAgentWorkflow:
    """Autonomous agent that executes a query, grades retrieved context,
    and self‑corrects up to ``max_retries`` times.

    The loop mirrors the “Retrieve‑Grade‑Rewrite” pattern common in
    production RAG systems.
    """

    max_retries: int = 3

    def __init__(
        self,
        engine: PostgresEngine,
        router: QueryRouter,
        top_k: int = 4,
    ) -> None:
        self.engine = engine
        self.router = router
        self.top_k = top_k
        self.retries = 0

    def run(self, user_query: str) -> Dict[str, Any]:
        """Execute the full self‑correction workflow and return a final answer
        dict containing ``answer`` and ``missing_info`` (if any)."""
        self.retries = 0
        while self.retries <= self.max_retries:
            self.retries += 1
            print(f"\n[Workflow] Attempt {self.retries}/{self.max_retries}")

            # Step A: route query & retrieve context
            optimized, filters = self.router.route(user_query)
            context_docs = self.engine.search(
                query_embedding=self._dummy_embedding(optimized),
                metadata_filters=filters,
                limit=self.top_k,
            )

            # Step B: fast LLM grader
            graded = self._grade_context(user_query, context_docs)

            if graded == "Yes":
                return self._synthesize(user_query, context_docs)

            # graded "No" → rewrite & loop
            print(
                f"[Workflow] Grader said 'No' (attempt {self.retries}). "
                "Rewriting query & loosening filters."
            )
            user_query = f"{user_query} *broaden*"
            filters = {}

        # Exhausted retries
        return {
            "answer": "",
            "missing_info": "Max retries exceeded; could not find relevant context.",
            "retries": self.retries,
        }

    @staticmethod
    def _grade_context(user_query: str, docs: List[Any]) -> str:
        """Heuristic grader: return ``"Yes"`` if any document contains key tokens
        from the query, otherwise ``"No"``."""
        if not docs:
            return "No"
        query_tokens = set(re.findall(r"[A-Za-z0-9]+", user_query.lower()))
        for d in docs:
            doc_text = (d.text or "").lower()
            if any(tk in doc_text for tk in query_tokens):
                return "Yes"
        return "No"

    @staticmethod
    def _synthesize(user_query: str, docs: List[Any]) -> Dict[str, Any]:
        """Produce a final answer using only the provided context snippets.
        If the context lacks required info, explicitly state what is missing."""
        if not docs:
            return {
                "answer": "",
                "missing_info": "No context documents were returned.",
            }

        snippets = "\n\n".join(
            f"[{i}] {d.text[:200]}..." for i, d in enumerate(docs[:3])
        )

        answer_parts: List[str] = []
        missing: List[str] = []

        date_match = re.search(r"\d{4}-\d{2}-\d{2}", snippets)
        if date_match:
            answer_parts.append(f"The records concern the date {date_match.group(0)}.")
        else:
            missing.append("exact date information")

        if answer_parts:
            answer = " ".join(answer_parts)
        else:
            answer = ""
            if not date_match:
                missing.append("date information")
            if not any("sales" in (txt or "").lower() for txt in docs):
                missing.append("sales‑related data")
            if not any("2024" in (txt or "") for txt in docs):
                missing.append("2024 references")

        return {
            "answer": answer if answer else "Insufficient context to formulate an answer.",
            "missing_info": "; ".join(missing) if missing else None,
        }

    @staticmethod
    def _dummy_embedding(text: str) -> List[float]:
        return RealTimeSyncWorker._fake_embedding(text)


# ----------------------------------------------------------------------
# 6️⃣  Demo / main entry point
# ----------------------------------------------------------------------


if __name__ == "__main__":
    # ------------------------------------------------------------------
    # Initialise configuration (SQLite in‑memory for the demo)
    # ------------------------------------------------------------------
    config = EnterpriseConfig(db_url="sqlite:///:memory:")

    # ------------------------------------------------------------------
    # Create the engine (tables, pgvector‑ready schema)
    # ------------------------------------------------------------------
    engine = PostgresEngine(config)

    # ------------------------------------------------------------------
    # Populate a mock ``cdc_events`` table so the sync worker has something
    # to read.  In a real deployment this table would be maintained by your
    # database's change‑capture mechanism.
    # ------------------------------------------------------------------
    samples = [
        {
            "title": "Q3 Sales Report",
            "body": "The Q3 sales numbers show a 12% increase driven by the Northeast region.",
            "category": "sales",
            "date": "2024-09-01",
        },
        {
            "title": "Product Launch",
            "body": "Acme Corp launched the new X1 widget, featuring AI‑optimized pricing.",
            "category": "product",
            "date": "2024-10-15",
        },
    ]

    # Ensure the cdc_events table exists (SQLite file‑based)
    with engine._engine.begin() as conn:
        Base.metadata.create_all(engine._engine, tables=[CdcEvent.__table__])
        session = Session(bind=conn)
        for i, p in enumerate(samples, start=1):
            session.add(CdcEvent(id=i, operation="insert", payload=json.dumps(p)))
        session.commit()
        session.close()

    # ------------------------------------------------------------------
    # Initialise the sync worker (starts a background polling thread)
    # ------------------------------------------------------------------
    import threading

    sync_worker = RealTimeSyncWorker(engine, poll_interval=0.5)

    worker_thread = threading.Thread(target=sync_worker.start, daemon=True)
    worker_thread.start()
    time.sleep(2)  # let the worker ingest the seeded events
    worker_thread.join(timeout=1)

    # ------------------------------------------------------------------
    # Initialise query router & workflow
    # ------------------------------------------------------------------
    router = QueryRouter(engine)
    workflow = EnterpriseAgentWorkflow(engine, router, top_k=3)

    # ------------------------------------------------------------------
    # Example ambiguous multi‑step user query
    # ------------------------------------------------------------------
    user_query = (
        "What were the sales figures for the Q3 period and can you tell me "
        "about any product launches that happened around the same time? "
        "Also, did the board approve any budget changes in 2024?"
    )

    print("\n=== User Query ===")
    print(user_query)
    print("\n--- Running EnterpriseAgentWorkflow ---\n")

    result = workflow.run(user_query)

    print("\n=== Final Result ===")
    print(json.dumps(result, indent=2))

    print("\n[Engine] Demo completed.")