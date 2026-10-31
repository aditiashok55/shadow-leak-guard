"""Langfuse tracing (Phase 2, U1) with a graceful no-op fallback.

Goal: map each pipeline layer to a Langfuse span carrying role, dropped/redacted
chunks, the decision, token counts, and latency — so any blocked response is fully
explorable in the Langfuse UI. If Langfuse isn't installed or no keys are set, the
pipeline runs unchanged (spans become no-ops) and JSON traces still work.

Config via environment (e.g. a .env file, see .env.example):
    LANGFUSE_PUBLIC_KEY=pk-lf-...
    LANGFUSE_SECRET_KEY=sk-lf-...
    LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted URL
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

# Optional .env loading (no hard dependency).
try:  # pragma: no cover
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _langfuse_enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


class _NoopSpan:
    """Stand-in span when Langfuse is disabled; supports the same tiny API."""

    def update(self, **_: Any) -> None:
        pass

    def end(self, **_: Any) -> None:
        pass


class Observer:
    """Thin, version-tolerant wrapper over a Langfuse trace.

    Only a minimal surface is used (trace -> spans) and every call is defensive,
    so SDK version drift or a missing backend never breaks the pipeline.
    """

    def __init__(self, name: str, user_role: str, metadata: dict | None = None):
        self._client = None
        self._trace = None
        self.enabled = False
        if not _langfuse_enabled():
            return
        try:  # pragma: no cover - requires network + keys
            from langfuse import Langfuse

            self._client = Langfuse(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )
            self._trace = self._client.trace(
                name=name,
                metadata={"role": user_role, **(metadata or {})},
                tags=[f"role:{user_role}"],
            )
            self.enabled = True
        except Exception:
            self._client = None
            self._trace = None
            self.enabled = False

    @contextmanager
    def span(self, name: str, **metadata: Any) -> Iterator[Any]:
        """Context manager yielding a span handle with .update(...)."""
        if not self.enabled or self._trace is None:
            yield _NoopSpan()
            return
        span = None
        try:  # pragma: no cover - requires backend
            span = self._trace.span(name=name, metadata=metadata)
        except Exception:
            span = None
        try:
            yield span if span is not None else _NoopSpan()
        finally:
            if span is not None:
                try:  # pragma: no cover
                    span.end()
                except Exception:
                    pass

    def final(self, output: str, blocked: bool, **metadata: Any) -> None:
        if not self.enabled or self._trace is None:
            return
        try:  # pragma: no cover
            self._trace.update(
                output=output, metadata={"blocked": blocked, **metadata}
            )
        except Exception:
            pass

    def flush(self) -> None:
        if self._client is not None:
            try:  # pragma: no cover
                self._client.flush()
            except Exception:
                pass
