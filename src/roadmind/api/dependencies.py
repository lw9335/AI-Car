from __future__ import annotations

from typing import Annotated

from fastapi import Header

from roadmind.domain.auth import Principal
from roadmind.domain.models import Role


def principal_from_headers(
    x_user_id: Annotated[str, Header()] = "demo-user",
    x_role: Annotated[Role, Header()] = Role.ADMIN,
    x_region: Annotated[str, Header()] = "south_china",
) -> Principal:
    return Principal(user_id=x_user_id, role=x_role, region=x_region)
