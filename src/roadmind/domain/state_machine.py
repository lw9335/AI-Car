from __future__ import annotations

from roadmind.domain.models import TimelineEvent, WorkOrder, WorkOrderStatus, utc_now


class InvalidTransition(ValueError):
    """Raised when a work-order lifecycle invariant would be violated."""


ALLOWED_TRANSITIONS: dict[WorkOrderStatus, set[WorkOrderStatus]] = {
    WorkOrderStatus.REPORTED: {WorkOrderStatus.TRIAGED},
    WorkOrderStatus.TRIAGED: {WorkOrderStatus.DIAGNOSING},
    WorkOrderStatus.DIAGNOSING: {
        WorkOrderStatus.WAITING_EXPERT,
        WorkOrderStatus.MANUAL_TAKEOVER,
    },
    WorkOrderStatus.WAITING_EXPERT: {
        WorkOrderStatus.DIAGNOSIS_CONFIRMED,
        WorkOrderStatus.REDIAGNOSIS_REQUIRED,
        WorkOrderStatus.MANUAL_TAKEOVER,
    },
    WorkOrderStatus.DIAGNOSIS_CONFIRMED: {WorkOrderStatus.FULFILLING},
    WorkOrderStatus.FULFILLING: {
        WorkOrderStatus.READY_FOR_SERVICE,
        WorkOrderStatus.REDIAGNOSIS_REQUIRED,
        WorkOrderStatus.MANUAL_TAKEOVER,
    },
    WorkOrderStatus.READY_FOR_SERVICE: {
        WorkOrderStatus.IN_SERVICE,
        WorkOrderStatus.REDIAGNOSIS_REQUIRED,
    },
    WorkOrderStatus.IN_SERVICE: {
        WorkOrderStatus.WAITING_CLOSE_APPROVAL,
        WorkOrderStatus.REDIAGNOSIS_REQUIRED,
    },
    WorkOrderStatus.REDIAGNOSIS_REQUIRED: {
        WorkOrderStatus.DIAGNOSING,
        WorkOrderStatus.MANUAL_TAKEOVER,
    },
    WorkOrderStatus.WAITING_CLOSE_APPROVAL: {
        WorkOrderStatus.CLOSED,
        WorkOrderStatus.IN_SERVICE,
    },
    WorkOrderStatus.CLOSED: set(),
    WorkOrderStatus.MANUAL_TAKEOVER: {
        WorkOrderStatus.DIAGNOSING,
        WorkOrderStatus.WAITING_CLOSE_APPROVAL,
    },
}


def transition(
    order: WorkOrder,
    target: WorkOrderStatus,
    *,
    actor: str,
    reason: str,
) -> WorkOrder:
    allowed = ALLOWED_TRANSITIONS[order.status]
    if target not in allowed:
        raise InvalidTransition(f"{order.status} -> {target} is not allowed")
    previous = order.status
    order.status = target
    order.updated_at = utc_now()
    order.timeline.append(
        TimelineEvent(
            event_type="status.changed",
            actor=actor,
            data={"from": previous, "to": target, "reason": reason},
        )
    )
    return order
