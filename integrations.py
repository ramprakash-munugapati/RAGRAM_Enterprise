# ----------------------------------------------------------------------
# integrations.py
# ----------------------------------------------------------------------
"""Generation back‑ends for RAGRAM Enterprise.

Each class implements :
    - generate(prompt: str) -> str                # plain answer
    - structured_output(prompt: str) -> dict     # forces JSON {optimized_query, metadata_filters}
"""
import json
import os
import re
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


# ----------------------------------------------------------------------
# Abstract base class
# ----------------------------------------------------------------------
class GenerationBackend(ABC):
    """All concrete back‑ends must implement these two methods."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Return a plain text answer produced *only* from the prompt."""
        raise NotImplementedError

    @abstractmethod
    def structured_output(self, prompt: str) -> Dict[str, Any]:
        """Force the LLM to return a JSON object.
        Expected keys: "optimized_query" (str) and "metadata_filters" (dict)."""
        raise NotImplementedError


# ----------------------------------------------------------------------
# 1️⃣  OpenAI backend
# ------------------------------------------------------------------
class OpenAIGeneration(GenerationBackend):
    """Wrap OpenAI ChatCompletion (gpt‑4o‑mini or gpt‑3.5‑turbo)."""
    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    def _chat(self, messages: List[Dict[str, str]]) -> str:
        import openai  # imported lazily – user must have openai installed
        resp = openai.ChatCompletion.create(
            model=self.model,
            messages=messages,
            temperature=0,
        )
        return resp.choices[0].message.content.strip()

    def generate(self, prompt: str) -> str:
        """Plain answer generation."""
        messages = [
            {"role": "system", "content": "You are a factual RAG answer generator."},
            {"role": "user", "content": prompt},
        ]
        return self._chat(messages)

    def structured_output(self, prompt: str) -> Dict[str, Any]:
        """Force the model to output JSON with keys optimized_query & metadata_filters."""
        system_msg = (
            "You are a RAG query‑rewriter. "
            "Respond with a single JSON object having the keys "
            "'optimized_query' (a cleaned search string) and "
            "'metadata_filters' (a dict of key/value pairs)."
        )
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ]
        raw = self._chat(messages)
        # The model may wrap the JSON in triple‑back‑quotes; strip them.
        raw = re.sub(r"^```json\s*|\```$", "", raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)
        # Minimal validation – fall back to defaults if something is missing.
        data.setdefault("optimized_query", prompt)
        data.setdefault("metadata_filters", {"category": "unspecified"})
        return data


# ----------------------------------------------------------------------
# 2️⃣  Anthropic backend
# ------------------------------------------------------------------
class AnthropicGeneration(GenerationBackend):
    """Wrap Anthropic messages.create (claude‑3‑haiku/sonnet)."""
    def __init__(self, model: str = "claude-3-haiku-20240307") -> None:
        self.model = model
        import anthropic  # lazy import
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def _chat(self, system: str, user: str) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Anthropic returns a block text; we just take the first block.
        return resp.content[0].text.strip()

    def generate(self, prompt: str) -> str:
        messages = [
            ("system", "You are a factual RAG answer generator."),
            ("user", prompt),
        ]
        return self._chat(*messages)

    def structured_output(self, prompt: str) -> Dict[str, Any]:
        system_msg = (
            "You are a RAG query‑rewriter. "
            "Respond with a single JSON object having the keys "
            "'optimized_query' (a cleaned search string) and "
            "'metadata_filters' (a dict of key/value pairs)."
        )
        user_msg = prompt
        raw = self._chat(system_msg, user_msg)
        raw = re.sub(r"^```json\s*|\```$", "", raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)
        data.setdefault("optimized_query", prompt)
        data.setdefault("metadata_filters", {"category": "unspecified"})
        return data


# ----------------------------------------------------------------------
# 3️⃣  Ollama backend (stdlib only – urllib.request)
# ------------------------------------------------------------------
class OllamaGeneration(GenerationBackend):
    """Talk to a local Ollama instance via its REST API.
    Uses only the Python standard library – no extra pip packages."""
    def __init__(self, base_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")) -> None:
        self.base_url = base_url.rstrip("/")

    def _post(self, payload: Dict[str, Any]) -> str:
        """POST to /api/chat and return the 'response' field."""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
        result = json.loads(body)
        return result.get("response", "")

    def generate(self, prompt: str) -> str:
        """Plain answer generation."""
        payload = {
            "model": "llama2",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        return self._post(payload)

    def structured_output(self, prompt: str) -> Dict[str, Any]:
        """Force Ollama to return JSON with the two required keys."""
        system_msg = (
            "You are a RAG query‑rewriter. "
            "Respond with a single JSON object having the keys "
            "'optimized_query' (a cleaned search string) and "
            "'metadata_filters' (a dict of key/value pairs)."
        )
        payload = {
            "model": "llama2",
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        raw = self._post(payload)
        # Ollama may wrap the JSON in markdown fences; strip them.
        raw = re.sub(r"^```json\s*|\```$", "", raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)
        data.setdefault("optimized_query", prompt)
        data.setdefault("metadata_filters", {"category": "unspecified"})
        return data


# ----------------------------------------------------------------------
# 4️⃣  Helper to pick a backend from the environment
# ----------------------------------------------------------------------
def load_backend(name: Optional[str] = None) -> GenerationBackend:
    """Factory that returns the requested backend instance.
    *name* can be "openai", "anthropic" or "ollama".  If *name* is None
    the value of the env var RAGMA_BACKEND is used (defaults to "openai")."""
    if name is None:
        name = os.getenv("RAGMA_BACKEND", "openai").lower()

    if name == "openai":
        return OpenAIGeneration()
    if name == "anthropic":
        return AnthropicGeneration()
    if name == "ollama":
        return OllamaGeneration()
    raise ValueError(f"Unknown generation backend: {name}")


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# LangChain retriever (extra [langchain])
# ----------------------------------------------------------------------
from langchain_core.retrievers import BaseRetriever as LCBaseRetriever
from langchain_core.documents import Document as LCDoc
from typing import List


class RagramLangChainRetriever(LCBaseRetriever):
    """A LangChain‑compatible retriever that wraps the RAGRAM engine.

    The `get_relevant_documents` method:
      1. Calls the engine’s `search` method with the user query.
      2. Returns a list of `langchain_core.documents.Document` objects.
    """
    def __init__(self, engine: PostgresEngine, top_k: int = 4) -> None:
        self.engine = engine
        self.top_k = top_k

    def get_relevant_documents(self, query: str) -> List[LCDoc]:
        # Use the same deterministic pseudo‑embedding that the engine uses
        # when no real embedding function is supplied.
        from RagramEnterpriseEngine import RealTimeSyncWorker
        emb = RealTimeSyncWorker._fake_embedding(query)

        docs = self.engine.search(
            query_embedding=emb,
            metadata_filters=None,
            limit=self.top_k,
        )
        # Convert ORM objects to LangChain Document objects
        return [
            LCDoc(page_content=doc.text, metadata=doc.metadata or {})
            for doc in docs
        ]


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# LlamaIndex retriever (extra [llamaindex])
# ----------------------------------------------------------------------
from llama_index.core.retrievers import BaseRetriever as LIBaseRetriever
from llama_index.core.schema import NodeWithScore
from typing import List as LiList


class RagramLlamaIndexRetriever(LIBaseRetriever):
    """LlamaIndex‑compatible retriever wrapping the RAGRAM engine."""

    def __init__(self, engine: PostgresEngine, top_k: int = 4) -> None:
        self.engine = engine
        self.top_k = top_k

    def retrieve(self, query: str) -> LiList[NodeWithScore]:
        # Same deterministic pseudo‑embedding as the LangChain wrapper
        from RagramEnterpriseEngine import RealTimeSyncWorker
        emb = RealTimeSyncWorker._fake_embedding(query)

        docs = self.engine.search(
            query_embedding=emb,
            metadata_filters=None,
            limit=self.top_k,
        )
        # LlamaIndex expects NodeWithScore objects; we create them from the ORM docs.
        nodes: LiList[NodeWithScore] = []
        for doc in docs:
            node = NodeWithScore(
                node=doc,                     # the ORM Document (will be serialised later)
                score=1.0,                    # similarity score – we don’t have a real one here
            )
            nodes.append(node)
        return nodes

# ----------------------------------------------------------------------
# End of integrations.py
# ----------------------------------------------------------------------