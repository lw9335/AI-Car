from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from roadmind.domain.models import WorkOrder, utc_now
from roadmind.infra.db import session_scope, work_orders


class WorkOrderNotFound(KeyError):
    pass


class OptimisticLockError(RuntimeError):
    pass


class WorkOrderRepository(Protocol):
    def create(self, order: WorkOrder) -> WorkOrder: ...

    def get(self, service_request_id: str) -> WorkOrder: ...

    def save(self, order: WorkOrder, *, expected_version: int | None = None) -> WorkOrder: ...

    def list(self) -> list[WorkOrder]: ...


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
            order.version = current.version + 1
            order.updated_at = utc_now()
            self._items[order.service_request_id] = deepcopy(order)
            return deepcopy(order)

    def list(self) -> list[WorkOrder]:
        with self._lock:
            return [deepcopy(item) for item in self._items.values()]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class PostgresWorkOrderRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sessions = session_factory

    def create(self, order: WorkOrder) -> WorkOrder:
        with session_scope(self._sessions) as session:
            existing = session.execute(
                select(work_orders.c.service_request_id).where(
                    work_orders.c.service_request_id == order.service_request_id
                )
            ).first()
            if existing:
                raise OptimisticLockError("duplicate service_request_id")
            payload = order.model_dump(mode="json")
            session.execute(
                work_orders.insert().values(
                    service_request_id=order.service_request_id,
                    version=order.version,
                    status=order.status.value,
                    payload=payload,
                    created_at=order.created_at,
                    updated_at=order.updated_at,
                )
            )
            return deepcopy(order)

    def get(self, service_request_id: str) -> WorkOrder:
        with session_scope(self._sessions) as session:
            row = (
                session.execute(
                    select(work_orders).where(
                        work_orders.c.service_request_id == service_request_id
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise WorkOrderNotFound(service_request_id)
            return WorkOrder.model_validate(row["payload"])

    def save(self, order: WorkOrder, *, expected_version: int | None = None) -> WorkOrder:
        with session_scope(self._sessions) as session:
            row = session.execute(
                select(work_orders.c.version).where(
                    work_orders.c.service_request_id == order.service_request_id
                )
            ).first()
            if row is None:
                raise WorkOrderNotFound(order.service_request_id)
            current_version = int(row[0])
            if expected_version is not None and current_version != expected_version:
                raise OptimisticLockError(
                    f"expected version {expected_version}, current version {current_version}"
                )
            order.version = current_version + 1
            order.updated_at = utc_now()
            result = session.execute(
                work_orders.update()
                .where(
                    work_orders.c.service_request_id == order.service_request_id,
                    work_orders.c.version == current_version,
                )
                .values(
                    version=order.version,
                    status=order.status.value,
                    payload=order.model_dump(mode="json"),
                    updated_at=order.updated_at,
                )
            )
            if result.rowcount != 1:
                raise OptimisticLockError(
                    f"expected version {expected_version}, current version changed concurrently"
                )
            return deepcopy(order)

    def list(self) -> list[WorkOrder]:
        with session_scope(self._sessions) as session:
            rows = session.execute(select(work_orders.c.payload)).scalars().all()
            return [WorkOrder.model_validate(payload) for payload in rows]
