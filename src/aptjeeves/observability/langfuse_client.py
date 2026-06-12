from __future__ import annotations

from typing import Any


class LangfuseClient:
    """Wrapper around the Langfuse SDK for tracing LLM calls in AptJeeves."""

    def __init__(self, *, secret_key: str, public_key: str, host: str) -> None:
        from langfuse import Langfuse

        self._lf = Langfuse(secret_key=secret_key, public_key=public_key, host=host)

    def trace(self, *, name: str, query_id: str) -> "LangfuseTrace":
        try:
            # Try Langfuse 2.0+ API: trace(name=..., id=...)
            lf_trace = self._lf.trace(name=name, id=query_id)
        except (AttributeError, TypeError):
            # Fall back to just name parameter if id is not supported
            try:
                lf_trace = self._lf.trace(name=name)
            except (AttributeError, TypeError):
                # If trace method doesn't exist, return a null trace
                return NullTrace()
        return LangfuseTrace(lf_trace)

    def flush(self) -> None:
        try:
            self._lf.flush()
        except (AttributeError, TypeError):
            pass  # Flush might not be available in all versions


class LangfuseTrace:
    """Thin wrapper around one Langfuse trace."""

    def __init__(self, trace: Any) -> None:
        self._trace = trace

    def start_generation(
        self,
        *,
        name: str,
        model: str,
        input: Any,
    ) -> "LangfuseGeneration":
        gen = self._trace.generation(name=name, model=model, input=input)
        return LangfuseGeneration(gen)

    def span(self, name: str) -> "LangfuseSpan":
        return LangfuseSpan(self._trace.span(name=name))


class LangfuseGeneration:
    def __init__(self, gen: Any) -> None:
        self._gen = gen

    def end(
        self,
        *,
        output: Any = None,
        usage: dict[str, int] | None = None,
        error: str | None = None,
    ) -> None:
        if error:
            self._gen.end(level="ERROR", status_message=error)
            return
        kwargs: dict[str, Any] = {"output": output}
        if usage:
            kwargs["usage"] = {"input": usage.get("input", 0), "output": usage.get("output", 0), "unit": "TOKENS"}
        self._gen.end(**kwargs)


class LangfuseSpan:
    def __init__(self, span: Any) -> None:
        self._span = span

    def end(self) -> None:
        self._span.end()


# ── Null objects used when Langfuse is not configured ─────────────────────


class NullLangfuseClient:
    """No-op Langfuse client used when observability is not configured."""

    def trace(self, **kwargs: Any) -> "NullTrace":
        return NullTrace()

    def flush(self) -> None:
        pass


class NullTrace:
    def start_generation(self, **kwargs: Any) -> "NullGeneration":
        return NullGeneration()

    def span(self, name: str) -> "NullSpan":
        return NullSpan()


class NullGeneration:
    def end(self, **kwargs: Any) -> None:
        pass


class NullSpan:
    def end(self) -> None:
        pass


def build_langfuse_client(
    *,
    secret_key: str | None,
    public_key: str | None,
    host: str | None,
) -> LangfuseClient | NullLangfuseClient:
    """Return a real LangfuseClient if keys are present, else a null client."""

    if secret_key and public_key and host:
        return LangfuseClient(secret_key=secret_key, public_key=public_key, host=host)
    return NullLangfuseClient()
