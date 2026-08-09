from __future__ import annotations

from typing import Any, Protocol

from roadmind.domain.auth import Principal
from roadmind.domain.models import (
    DiagnosisPackage,
    DispatchCandidate,
    PartCandidate,
    WorkOrder,
)


class LeaseConflict(RuntimeError):
    """Raised when a short-lived resource lease belongs to another work order."""


class ResourceLease(Protocol):
    """Short-lived resource reservation boundary implemented in memory or Redis."""

    def reserve(self, resource_id: str, order_id: str, *, ttl_seconds: int = 120) -> None: ...

    def release(self, resource_id: str, order_id: str) -> None: ...


class DiagnosisCapability(Protocol):
    """Deterministic domain capability used by the after-sales workflow."""

    def diagnose(self, order: WorkOrder) -> DiagnosisPackage: ...


class DispatchCapability(Protocol):
    """Resource planning and reservation port; implementations may use OR-Tools."""

    def candidates(self, order: WorkOrder) -> list[DispatchCandidate]: ...

    def reserve(self, order: WorkOrder, resource_id: str) -> None: ...

    def release(self, resource_id: str, order_id: str) -> None: ...

    def verify_assignment(self, order: WorkOrder, resource_id: str) -> None: ...


class PartsCapability(Protocol):
    """Transactional parts recommendation and reservation port."""

    def candidates(
        self, order: WorkOrder, *, stock: dict[str, int] | None = None
    ) -> list[PartCandidate]: ...

    def reserve(self, order_id: str, part_codes: list[str]) -> None: ...

    def release(self, order_id: str) -> list[str]: ...

    def snapshot(self) -> dict[str, int]: ...


class OperationsCapability(Protocol):
    """Whitelisted metrics query port; it never accepts generated SQL."""

    def answer(
        self,
        question: str,
        orders: list[WorkOrder],
        *,
        principal: Principal,
        scenario_delta: float | None = None,
    ) -> dict[str, Any]: ...
