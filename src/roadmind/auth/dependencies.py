from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from roadmind.auth.users import decode_access_token
from roadmind.domain.auth import Principal
from roadmind.domain.models import Role
from roadmind.settings import get_settings

_bearer = HTTPBearer(auto_error=False)


def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_role: Annotated[Role | None, Header()] = None,
    x_region: Annotated[str | None, Header()] = None,
) -> Principal:
    settings = get_settings()

    if credentials and credentials.scheme.lower() == "bearer":
        try:
            payload = decode_access_token(credentials.credentials, secret=settings.jwt_secret)
        except Exception as exc:
            raise HTTPException(status_code=401, detail="invalid_token") from exc
        return Principal(
            user_id=str(payload["sub"]),
            role=Role(str(payload["role"])),
            region=str(payload.get("region") or "south_china"),
        )

    if settings.allow_header_auth and x_role is not None:
        return Principal(
            user_id=x_user_id or "demo-user",
            role=x_role,
            region=x_region or "south_china",
        )

    raise HTTPException(status_code=401, detail="authentication_required")
