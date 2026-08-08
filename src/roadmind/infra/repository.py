from __future__ import annotations

from copy import deepcopy
from threading import RLock

from roadmind.domain.models import WorkOrder, utc_now


class WorkOrderNotFound(KeyError):
    pass


class OptimisticLockError(RuntimeError):
    pass


class InMemoryWorkOrderRepository:
    """Thread-safe adapter that preserves the same optimistic-lock contract as PostgreSQL."""

    def __init__(self) -> None:
        self._items: dict[str, WorkOrder] = {}
        self._lock = RLock()

    def create(self, order: WorkOrder) -> WorkOrder:
        with self._lock:
            if order.service_request_id in self._items:
                raise OptimisticLockError("duplicate service_request_id")
            self._items[order.service_request_id] = deepcopy(order)
            return deepcopy(order)

    def get(self, service_request_id: str) -> WorkOrder:
        with self._lock:
            try:
                return deepcopy(self._items[service_request_id])
            except KeyError as exc:
                raise WorkOrderNotFound(service_request_id) from exc

    def save(self, order: WorkOrder, *, expected_version: int | None = None) -> WorkOrder:
        with self._lock:
            current = self._items.get(order.service_request_id)
            if current is None:
                raise WorkOrderNotFound(order.service_request_id)
            if expected_version is not None and current.version != expected_version:
                raise OptimisticLockError(
                    f"expected version {expected_version}, current version {current.version}"
                )
            order.updated_at = utc_now()
            self._items[order.service_request_id] = deepcopy(order)
            return deepcopy(order)

    def list(self) -> list[WorkOrder]:
        with self._lock:
            return [deepcopy(item) for item in self._items.values()]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
