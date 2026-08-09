from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from roadmind.domain.models import utc_now
from roadmind.infra.db import outbox_messages, session_scope


@dataclass
class OutboxMessage:
    topic: str
    payload: dict[str, Any]
    message_id: str = field(default_factory=lambda: f"msg_{uuid4().hex[:12]}")
    created_at: datetime = field(default_factory=utc_now)
    delivered: bool = False


class OutboxStore(Protocol):
    def append(self, topic: str, payload: dict[str, Any]) -> OutboxMessage: ...

    def pending(self) -> list[OutboxMessage]: ...

    def deliver(self, publisher: Callable[[OutboxMessage], None]) -> int: ...


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


class PostgresTransactionalOutbox:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sessions = session_factory

    def append(self, topic: str, payload: dict[str, Any]) -> OutboxMessage:
        message = OutboxMessage(topic=topic, payload=payload)
        with session_scope(self._sessions) as session:
            session.execute(
                outbox_messages.insert().values(
                    message_id=message.message_id,
                    topic=message.topic,
                    payload=message.payload,
                    created_at=message.created_at,
                    delivered=False,
                )
            )
        return message

    def pending(self) -> list[OutboxMessage]:
        with session_scope(self._sessions) as session:
            rows = (
                session.execute(
                    select(outbox_messages).where(outbox_messages.c.delivered.is_(False))
                )
                .mappings()
                .all()
            )
            return [
                OutboxMessage(
                    message_id=row["message_id"],
                    topic=row["topic"],
                    payload=dict(row["payload"]),
                    created_at=row["created_at"],
                    delivered=bool(row["delivered"]),
                )
                for row in rows
            ]

    def deliver(self, publisher: Callable[[OutboxMessage], None]) -> int:
        messages = self.pending()
        delivered = 0
        for message in messages:
            publisher(message)
            with session_scope(self._sessions) as session:
                session.execute(
                    outbox_messages.update()
                    .where(outbox_messages.c.message_id == message.message_id)
                    .values(delivered=True)
                )
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
