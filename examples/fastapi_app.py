# ----------------------------------------------------------------------
# examples/fastapi_app.py
# ----------------------------------------------------------------------
import os
import json
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Load optional .env file (python‑dotenv)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

from RagramEnterpriseEngine import (
    EnterpriseConfig,
    PostgresEngine,
    RealTimeSyncWorker,
    QueryRouter,
    EnterpriseAgentWorkflow,
    load_backend,
)

# ------------------------------------------------------------------
# Initialise everything once at startup
# ------------------------------------------------------------------
config = EnterpriseConfig(db_url=os.getenv("DB_URL", "sqlite:///:memory:"))
engine = PostgresEngine(config)                     # embedding function will be added later
router = QueryRouter(engine)

# Choose the generation backend via the env var RAGMA_BACKEND
backend = load_backend(os.getenv("RAGMA_BACKEND"))   # OpenAI, Anthropic or Ollama

workflow = EnterpriseAgentWorkflow(
    engine,
    router,
    top_k=3,
    grader=lambda q, d: "Yes" if "yes" in _openai_grader_simple(q, d).lower() else "No",
    synthesizer=lambda q, d: backend.generate(q),
)

# ------------------------------------------------------------------
# Helper – a very small grader that just looks for key tokens.
# In production you would replace this with the proper backend grader.
# ----------------------------------------------------------------------
def _openai_grader_simple(query: str, docs: List[Any]) -> str:
    tokens = set(re.findall(r"[A-Za-z0-9]+", query.lower()))
    for d in docs:
        txt = (d.text or "").lower()
        if any(tk in txt for tk in tokens):
            return "Yes"
    return "No"

# ------------------------------------------------------------------
# Pydantic models for the API
# ------------------------------------------------------------------
class Query(BaseModel):
    question: str

class Answer(BaseModel):
    answer: str
    missing_info: Optional[str] = None
    retries: int = 0

# ------------------------------------------------------------------
# FastAPI endpoint
# ------------------------------------------------------------------
app = FastAPI(title="RAGRAM Enterprise API")

@app.on_event("startup")
def startup_event():
    # Seed the mock cdc_events table so the worker has something to read
    with engine._engine.begin() as conn:
        Base.metadata.create_all(engine._engine, tables=[CdcEvent.__table__])
        import json as _json
        samples = [
            {
                "title": "Q3 Sales Report",
                "body": "The Q3 sales numbers show a 12% increase driven by the Northeast region.",
                "category": "sales",
                "date": "2024-09-01",
            },
        ]
        import sqlalchemy as sa
        session = sa.orm.Session(bind=conn)
        for i, p in enumerate(samples, start=1):
            from RagramEnterpriseEngine import CdcEvent
            session.add(CdcEvent(id=i, operation="insert", payload=_json.dumps(p)))
        session.commit()
        session.close()

@app.post("/query", response_model=Answer)
def query_endpoint(q: Query):
    try:
        result = workflow.run(q.question)
        return Answer(
            answer=result.get("answer", ""),
            missing_info=result.get("missing_info"),
            retries=result.get("retries", 0),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

# ------------------------------------------------------------------
# Run the server (uvicorn) when the file is executed directly
# ------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("examples.fastapi_app:app", host="0.0.0.0", port=8000, reload=True)