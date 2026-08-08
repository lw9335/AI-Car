from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from roadmind.domain.models import utc_now


@dataclass
class OutboxMessage:
    topic: str
    payload: dict[str, Any]
    message_id: str = field(default_factory=lambda: f"msg_{uuid4().hex[:12]}")
    created_at: datetime = field(default_factory=utc_now)
    delivered: bool = False


class TransactionalOutbox:
    def __init__(self) -> None:
        self._messages: list[OutboxMessage] = []
        self._lock = RLock()

    def append(self, topic: str, payload: dict[str, Any]) -> OutboxMessage:
        message = OutboxMessage(topic=topic, payload=payload)
        with self._lock:
            self._messages.append(message)
        return message

    def pending(self) -> list[OutboxMessage]:
        with self._lock:
            return [message for message in self._messages if not message.delivered]

    def deliver(self, publisher: Callable[[OutboxMessage], None]) -> int:
        delivered = 0
        with self._lock:
            for message in self._messages:
                if message.delivered:
                    continue
                publisher(message)
                message.delivered = True
                delivered += 1
        return delivered


@dataclass
class SagaStep:
    name: str
    compensate: Callable[[], None]


class Saga:
    """Records compensations and executes them in reverse order on partial failure."""

    def __init__(self) -> None:
        self._completed: list[SagaStep] = []

    def record(self, name: str, compensate: Callable[[], None]) -> None:
        self._completed.append(SagaStep(name=name, compensate=compensate))

    def compensate_all(self) -> list[str]:
        compensated = []
        while self._completed:
            step = self._completed.pop()
            step.compensate()
            compensated.append(step.name)
        return compensated
