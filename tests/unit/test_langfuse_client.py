from __future__ import annotations

from aptjeeves.observability.langfuse_client import (
    NullLangfuseClient,
    NullGeneration,
    NullTrace,
    build_langfuse_client,
)


def test_null_client_trace_returns_null_trace():
    client = NullLangfuseClient()
    trace = client.trace(name="test", query_id="q1")
    assert isinstance(trace, NullTrace)


def test_null_trace_generation_returns_null_generation():
    trace = NullTrace()
    gen = trace.start_generation(name="gen", model="gpt-4.1-mini", input=[])
    assert isinstance(gen, NullGeneration)


def test_null_generation_end_is_noop():
    gen = NullGeneration()
    gen.end(output="test", usage={"input": 10, "output": 5})  # Should not raise


def test_null_client_flush_is_noop():
    client = NullLangfuseClient()
    client.flush()  # Should not raise


def test_build_langfuse_client_returns_null_when_no_keys():
    client = build_langfuse_client(secret_key=None, public_key=None, host=None)
    assert isinstance(client, NullLangfuseClient)


def test_build_langfuse_client_returns_null_when_partial_keys():
    client = build_langfuse_client(secret_key="sk", public_key=None, host=None)
    assert isinstance(client, NullLangfuseClient)
