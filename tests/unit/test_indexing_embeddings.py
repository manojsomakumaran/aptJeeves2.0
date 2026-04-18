from __future__ import annotations

import json

from aptjeeves.indexing.embeddings import LocalTokenEmbeddingModel


def test_local_token_embedding_is_deterministic_and_normalized() -> None:
    model = LocalTokenEmbeddingModel()

    first = model.embed_json("Plumber plumber PHONE_1")
    second = model.embed_json("Plumber plumber PHONE_1")
    vector = json.loads(first)

    assert first == second
    assert set(vector) == {"phone_1", "plumber"}
    assert vector["plumber"] > vector["phone_1"]
