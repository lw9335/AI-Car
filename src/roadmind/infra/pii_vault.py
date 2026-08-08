from __future__ import annotations

from threading import RLock
from uuid import uuid4


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
