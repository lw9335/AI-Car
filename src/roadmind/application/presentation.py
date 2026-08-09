from __future__ import annotations

from typing import Any

from roadmind.domain.auth import Principal
from roadmind.domain.models import Role, WorkOrder


def present_work_order(order: WorkOrder, principal: Principal) -> dict[str, Any]:
    """Serialize a work order while preserving approval-token visibility rules."""

    data = order.model_dump(mode="json")
    for approval in data["approvals"]:
        can_view_token = (
            principal.role == Role.ADMIN or approval["requested_role"] == principal.role
        )
        if not can_view_token:
            approval["token"] = "***"
    return data
