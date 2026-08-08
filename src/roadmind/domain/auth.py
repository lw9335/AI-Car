from __future__ import annotations

from dataclasses import dataclass

from roadmind.domain.models import Role


class PermissionDenied(PermissionError):
    pass


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: Role
    region: str = "south_china"


ROLE_SCOPES: dict[Role, set[str]] = {
    Role.INFORMATION_OFFICER: {"workorder:read", "workorder:create", "diagnosis:run"},
    Role.TECHNICIAN: {"workorder:read", "diagnosis:run", "service:execute"},
    Role.EXPERT: {
        "workorder:read",
        "diagnosis:confirm",
        "diagnosis:run",
        "service:close_approve",
    },
    Role.DISPATCHER: {"workorder:read", "dispatch:read", "dispatch:approve"},
    Role.PARTS_MANAGER: {"workorder:read", "parts:read", "parts:reserve"},
    Role.OPERATIONS: {"workorder:read", "metrics:query", "metrics:simulate"},
    Role.ADMIN: {"*"},
}


def require_scope(principal: Principal, scope: str) -> None:
    scopes = ROLE_SCOPES[principal.role]
    if "*" not in scopes and scope not in scopes:
        raise PermissionDenied(f"role={principal.role} lacks scope={scope}")
