from __future__ import annotations

from typing import Any
from langfuse import Langfuse


class NullGeneration:
    def end(self, output: Any = None, usage: dict[str, Any] | None = None, **kwargs: Any) -> None:
        pass


class NullTrace:
    def start_generation(self, name: str, model: str, input: Any, **kwargs: Any) -> NullGeneration:
        return NullGeneration()


class NullLangfuseClient:
    def trace(self, name: str, query_id: str | None = None, **kwargs: Any) -> NullTrace:
        return NullTrace()

    def flush(self) -> None:
        pass


def build_langfuse_client(
    secret_key: str | None = None,
    public_key: str | None = None,
    host: str | None = None,
) -> Langfuse | NullLangfuseClient:
    if secret_key and public_key:
        return Langfuse(
            secret_key=secret_key,
            public_key=public_key,
            host=host or "https://cloud.langfuse.com",
        )
    return NullLangfuseClient()
