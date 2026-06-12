from __future__ import annotations

from aptjeeves.indexing.embeddings import _sparse_cosine


def test_cosine_identical_vectors() -> None:
    v = {"plumber": 0.5, "contact": 0.5}
    assert abs(_sparse_cosine(v, v) - 1.0) < 1e-6


def test_cosine_orthogonal_vectors() -> None:
    a = {"plumber": 1.0}
    b = {"electrician": 1.0}
    assert _sparse_cosine(a, b) == 0.0


def test_cosine_partial_overlap() -> None:
    a = {"plumber": 0.5, "contact": 0.5}
    b = {"plumber": 0.5, "repair": 0.5}
    sim = _sparse_cosine(a, b)
    assert 0 < sim < 1


def test_cosine_empty_vector() -> None:
    assert _sparse_cosine({}, {"a": 1.0}) == 0.0
    assert _sparse_cosine({"a": 1.0}, {}) == 0.0

