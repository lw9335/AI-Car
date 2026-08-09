from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from roadmind.auth.dependencies import get_principal
from roadmind.domain.auth import Principal, require_scope
from roadmind.mcp.gateway import McpGateway, ToolGateway
from roadmind.mcp.protocol import McpProtocolHandler

router = APIRouter()
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def gateway_from_request(request: Request) -> ToolGateway:
    return request.app.state.tool_gateway


Gateway = Annotated[ToolGateway, Depends(gateway_from_request)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "roadmind-mcp-gateway", "version": "0.1.0"}


@router.post("/mcp")
def mcp_endpoint(
    payload: dict[str, Any],
    request: Request,
    principal: CurrentPrincipal,
    gateway: Gateway,
) -> Response:
    origin = request.headers.get("origin")
    settings = request.app.state.settings
    if origin and origin not in settings.cors_origin_list:
        raise HTTPException(status_code=403, detail="origin_not_allowed")

    accept = request.headers.get("accept", "")
    accepted = {item.split(";", 1)[0].strip() for item in accept.split(",")}
    required = {"application/json", "text/event-stream"}
    if "*/*" not in accepted and not required.issubset(accepted):
        raise HTTPException(status_code=406, detail="mcp_accept_header_required")

    response = McpProtocolHandler(gateway).handle(
        payload,
        principal=principal,
        protocol_version=request.headers.get("mcp-protocol-version"),
        mcp_method=request.headers.get("mcp-method"),
        mcp_name=request.headers.get("mcp-name"),
    )
    if response.body is None:
        return Response(status_code=response.status_code)
    return JSONResponse(status_code=response.status_code, content=response.body)


@router.get("/management/tool-audit")
def tool_audit(principal: CurrentPrincipal, gateway: Gateway) -> list[dict[str, Any]]:
    require_scope(principal, "*")
    if not isinstance(gateway, McpGateway):
        raise HTTPException(status_code=503, detail="local_audit_store_unavailable")
    return gateway.audit_log(principal)
