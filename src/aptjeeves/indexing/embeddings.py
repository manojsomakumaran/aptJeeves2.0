from __future__ import annotations

import json
import math
import re
from collections import Counter


LOCAL_EMBEDDING_MODEL_VERSION = "local_token_vector_v1"


class LocalTokenEmbeddingModel:
    """Deterministic token-vector model used until real embeddings are added."""

    model_version = LOCAL_EMBEDDING_MODEL_VERSION

    def embed(self, text: str) -> dict[str, float]:
        """Return a normalized bag-of-words vector."""

        counts = Counter(_tokens(text))
        if not counts:
            return {}
        norm = math.sqrt(sum(value * value for value in counts.values()))
        return {token: round(count / norm, 6) for token, count in sorted(counts.items())}

    def embed_json(self, text: str) -> str:
        """Return deterministic JSON for the local vector."""

        return json.dumps(self.embed(text), sort_keys=True, separators=(",", ":"))

    def similarity(self, a_json: str, b_json: str) -> float:
        """Cosine similarity between two JSON-serialized sparse vectors."""

        a: dict[str, float] = json.loads(a_json)
        b: dict[str, float] = json.loads(b_json)
        return _sparse_cosine(a, b)


def _tokens(text: str) -> list[str]:
    """Tokenize retrieval text into lowercase alphanumeric terms."""

    return re.findall(r"[a-z0-9_]+", text.casefold())


def _sparse_cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity for two sparse vectors represented as dicts."""

    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
