from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from roadmind.domain.models import utc_now

_active_span: ContextVar[str | None] = ContextVar("active_span", default=None)


@dataclass
class Span:
    name: str
    kind: str
    metadata: dict[str, Any]
    span_id: str = field(default_factory=lambda: f"span_{uuid4().hex[:12]}")
    parent_id: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    ended_at: datetime | None = None
    status: str = "running"
    error: str | None = None


class TraceRecorder:
    """Local trace tree; production deployments can mirror spans to LangSmith."""

    def __init__(self) -> None:
        self._spans: list[Span] = []
        self._lock = RLock()

    @contextmanager
    def span(self, name: str, kind: str, **metadata: Any) -> Iterator[Span]:
        span = Span(name=name, kind=kind, metadata=metadata, parent_id=_active_span.get())
        token = _active_span.set(span.span_id)
        with self._lock:
            self._spans.append(span)
        try:
            yield span
            span.status = "ok"
        except Exception as exc:
            span.status = "error"
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            span.ended_at = utc_now()
            _active_span.reset(token)

    def list(self, service_request_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            spans = self._spans
            if service_request_id:
                spans = [
                    span
                    for span in spans
                    if span.metadata.get("service_request_id") == service_request_id
                ]
            return [asdict(span) for span in spans]

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()
