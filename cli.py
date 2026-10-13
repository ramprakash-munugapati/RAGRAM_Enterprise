import argparse
import json
import sys
import time
import threading

from RagramEnterpriseEngine import (
    EnterpriseConfig,
    PostgresEngine,
    RealTimeSyncWorker,
    QueryRouter,
    EnterpriseAgentWorkflow,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAGRAM Enterprise demo CLI")
    parser.add_argument(
        "--db-url",
        default="sqlite:///:memory:",
        help="SQLAlchemy DB URL",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed the in‑memory CDC table",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="User query to run through the workflow",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    cfg = EnterpriseConfig(db_url=args.db_url)
    engine = PostgresEngine(cfg)

    # ----- seed CDC table if requested -----
    if args.seed:
        with engine._engine.begin() as conn:
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
            for i, p in enumerate(samples, start=1):
                conn.execute(
                    sa.text("INSERT INTO cdc_events (id, operation, payload) VALUES (:id, :op, :payload)"),
                    {"id": i, "op": "insert", "payload": json.dumps(p)},
                )
        print("[CLI] CDC table seeded.")

    # ----- start sync worker (short burst) -----
    worker = RealTimeSyncWorker(engine, poll_interval=0.5)
    t = threading.Thread(target=worker.start, daemon=True)
    t.start()
    time.sleep(1.5)
    t.join(timeout=2)

    # ----- run a query through the agentic loop -----
    router = QueryRouter(engine)
    workflow = EnterpriseAgentWorkflow(engine, router, top_k=3)

    query = args.query or (
        "What were the sales figures for the Q3 period and can you tell me "
        "about any product launches that happened around the same time?"
    )
    result = workflow.run(query)

    print("\n=== Workflow result ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()