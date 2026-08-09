from __future__ import annotations

from fastapi import Request

from roadmind.application.service import RoadMindService
from roadmind.assistant.service import EnterpriseAssistantService
from roadmind.auth.dependencies import get_principal
from roadmind.mcp.gateway import ToolGateway


def service_from_request(request: Request) -> RoadMindService:
    return request.app.state.roadmind


def gateway_from_request(request: Request) -> ToolGateway:
    return request.app.state.tool_gateway


def assistant_from_request(request: Request) -> EnterpriseAssistantService:
    return request.app.state.enterprise_assistant


# Backwards-compatible alias used by older tests/imports.
principal_from_headers = get_principal
