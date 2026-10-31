"""Minimal JSON span logging. Every pipeline step emits one span."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import TRACES_DIR


@dataclass
class Trace:
    """Collects spans for one pipeline run and writes them to traces/<run_id>.json."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    spans: list[dict[str, Any]] = field(default_factory=list)

    def span(self, step: str, **data: Any) -> None:
        """Record a single step. `data` is merged into the span verbatim."""
        self.spans.append({"run_id": self.run_id, "step": step, **data})

    def timed(self, step: str) -> "_SpanTimer":
        return _SpanTimer(self, step)

    def save(self) -> Path:
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        path = TRACES_DIR / f"{self.run_id}.json"
        path.write_text(json.dumps(self.spans, indent=2))
        return path

    def pretty(self) -> str:
        return json.dumps(self.spans, indent=2)


class _SpanTimer:
    """Context manager that measures latency_ms and appends extra fields on exit."""

    def __init__(self, trace: Trace, step: str) -> None:
        self._trace = trace
        self._step = step
        self._extra: dict[str, Any] = {}
        self._start = 0.0

    def __enter__(self) -> "_SpanTimer":
        self._start = time.perf_counter()
        return self

    def set(self, **data: Any) -> None:
        self._extra.update(data)

    def __exit__(self, *exc: Any) -> None:
        latency_ms = round((time.perf_counter() - self._start) * 1000, 2)
        self._trace.span(self._step, latency_ms=latency_ms, **self._extra)
