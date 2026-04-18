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


def _tokens(text: str) -> list[str]:
    """Tokenize retrieval text into lowercase alphanumeric terms."""

    return re.findall(r"[a-z0-9_]+", text.casefold())
