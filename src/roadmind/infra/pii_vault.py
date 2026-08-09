from __future__ import annotations

from threading import RLock
from typing import Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from roadmind.infra.db import pii_subjects, session_scope


class PiiStore(Protocol):
    def put(self, value: dict[str, str]) -> str: ...

    def reveal(self, reference: str, *, authorized: bool) -> dict[str, str]: ...


class PiiVault:
    """Keeps direct identifiers outside the L0 agent-visible work-order state."""

    def __init__(self) -> None:
        self._values: dict[str, dict[str, str]] = {}
        self._lock = RLock()

    def put(self, value: dict[str, str]) -> str:
        reference = f"pii_{uuid4().hex[:16]}"
        with self._lock:
            self._values[reference] = dict(value)
        return reference

    def reveal(self, reference: str, *, authorized: bool) -> dict[str, str]:
        if not authorized:
            raise PermissionError("PII reveal requires explicit authorization")
        with self._lock:
            return dict(self._values[reference])


class PostgresPiiVault:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sessions = session_factory

    def put(self, value: dict[str, str]) -> str:
        reference = f"pii_{uuid4().hex[:16]}"
        with session_scope(self._sessions) as session:
            session.execute(pii_subjects.insert().values(reference=reference, payload=dict(value)))
        return reference

    def reveal(self, reference: str, *, authorized: bool) -> dict[str, str]:
        if not authorized:
            raise PermissionError("PII reveal requires explicit authorization")
        with session_scope(self._sessions) as session:
            row = session.execute(
                select(pii_subjects.c.payload).where(pii_subjects.c.reference == reference)
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(reference)
            return dict(row)
