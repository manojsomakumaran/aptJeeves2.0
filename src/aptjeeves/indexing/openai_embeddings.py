from __future__ import annotations

import json
import math


OPENAI_EMBEDDING_MODEL_VERSION_PREFIX = "openai"


class OpenAIEmbeddingModel:
    """Semantic embedding model using OpenAI text-embedding-3-small (or similar)."""

    def __init__(self, *, api_key: str, model: str = "text-embedding-3-small") -> None:
        import openai

        self._client = openai.OpenAI(api_key=api_key)
        self._model = model
        self.model_version = f"{OPENAI_EMBEDDING_MODEL_VERSION_PREFIX}_{model}_v1"

    def embed(self, text: str) -> list[float]:
        """Return a dense embedding vector for the given text."""

        response = self._client.embeddings.create(input=text, model=self._model)
        return response.data[0].embedding

    def embed_json(self, text: str) -> str:
        """Return JSON-serialized dense embedding for storage."""

        return json.dumps(self.embed(text))

    def similarity(self, a_json: str, b_json: str) -> float:
        """Cosine similarity between two JSON-serialized dense vectors."""

        a: list[float] = json.loads(a_json)
        b: list[float] = json.loads(b_json)
        return _dense_cosine(a, b)


def _dense_cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity for two dense float vectors."""

    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
