import json
import pytest
import threading

from RagramEnterpriseEngine import (
    EnterpriseConfig,
    PostgresEngine,
    RealTimeSyncWorker,
    QueryRouter,
    EnterpriseAgentWorkflow,
)


def test_basic_crud_and_search():
    cfg = EnterpriseConfig(db_url="sqlite:///:memory:")
    eng = PostgresEngine(cfg)

    doc = eng.upsert_document(
        text="Apples are fruit.",
        metadata={"category": "produce"},
        embedding=[0.5] * 768,
    )
    assert doc.id is not None
    assert doc.text == "Apples are fruit."

    results = eng.search(
        query_embedding=[0.5] * 768,
        metadata_filters={"category": "produce"},
        limit=2,
    )
    assert len(results) >= 1
    assert results[0].text == "Apples are fruit."


def test_sync_worker_ingests():
    cfg = EnterpriseConfig(db_url="sqlite:///:memory:")
    eng = PostgresEngine(cfg)

    with engine._engine.begin() as conn:  # type: ignore
        conn.execute(
            sa.text(
                """
        CREATE TABLE IF NOT EXISTS cdc_events (
            id INTEGER PRIMARY KEY,
            operation TEXT,
            payload JSONB
        );
        """
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO cdc_events (id, operation, payload) VALUES (1, 'insert', '{\"title\":\"Test\",\"body\":\"Hello world\",\"category\":\"demo\"}')"
            )
        )

    worker = RealTimeSyncWorker(engine, poll_interval=0.2)
    t = threading.Thread(target=worker.start, daemon=True)
    t.start()
    time.sleep(1)
    t.join(timeout=2)
    assert worker._processed


def test_query_router_returns_structured():
    cfg = EnterpriseConfig(db_url="sqlite:///:memory:")
    eng = PostgresEngine(cfg)
    router = QueryRouter(eng)

    optimized, filters = router.route("Can you give me the sales numbers for Q3 2024?")
    assert isinstance(optimized, str) and optimized.strip()
    assert isinstance(filters, dict)


def test_self_correction_loop_runs():
    cfg = EnterpriseConfig(db_url="sqlite:///:memory:")
    eng = PostgresEngine(cfg)

    for i, txt in enumerate(["Q3 sales increased 12%", "Product X launch in Oct"], start=1):
        eng.upsert_document(
            text=txt,
            metadata={"category": "sales" if i == 1 else "product"},
            embedding=[0.5] * 768,
        )

    router = QueryRouter(eng)
    workflow = EnterpriseAgentWorkflow(eng, router, top_k=2)

    result = workflow.run("What were the Q3 sales figures?")
    assert isinstance(result, dict)
    assert "answer" in result or "missing_info" in result