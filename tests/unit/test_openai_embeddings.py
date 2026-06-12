from __future__ import annotations

from unittest.mock import MagicMock, patch

from aptjeeves.indexing.openai_embeddings import OpenAIEmbeddingModel, _dense_cosine


def test_dense_cosine_identical():
    v = [1.0, 0.0, 0.0]
    assert abs(_dense_cosine(v, v) - 1.0) < 1e-6


def test_dense_cosine_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert _dense_cosine(a, b) == 0.0


def test_dense_cosine_empty():
    assert _dense_cosine([], [1.0]) == 0.0


def test_openai_embed_json_calls_api():
    with patch("openai.OpenAI") as mock_cls:
        mock_client = mock_cls.return_value
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1, 0.2, 0.3]
        mock_client.embeddings.create.return_value = MagicMock(data=[mock_embedding])

        model = OpenAIEmbeddingModel(api_key="test-key", model="text-embedding-3-small")
        json_str = model.embed_json("test sentence")

    import json
    result = json.loads(json_str)
    assert result == [0.1, 0.2, 0.3]
    mock_client.embeddings.create.assert_called_once_with(
        input="test sentence", model="text-embedding-3-small"
    )


def test_openai_model_version_format():
    with patch("openai.OpenAI"):
        model = OpenAIEmbeddingModel(api_key="x", model="text-embedding-3-small")
    assert "openai" in model.model_version
    assert "text-embedding-3-small" in model.model_version


def test_openai_similarity_uses_cosine():
    with patch("openai.OpenAI") as mock_cls:
        mock_client = mock_cls.return_value
        model = OpenAIEmbeddingModel(api_key="x")

    import json
    a = json.dumps([1.0, 0.0])
    b = json.dumps([1.0, 0.0])
    assert abs(model.similarity(a, b) - 1.0) < 1e-6
