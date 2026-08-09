from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from roadmind.application.service import RoadMindService
from roadmind.assistant.models import (
    AssistantChatRequest,
    AssistantChatResponse,
    ConversationView,
)
from roadmind.assistant.service import EnterpriseAssistantService, build_assistant_service
from roadmind.assistant.store import ConversationNotFound
from roadmind.auth.dependencies import get_principal
from roadmind.bootstrap import build_container
from roadmind.domain.auth import PermissionDenied, Principal
from roadmind.domain.state_machine import InvalidTransition
from roadmind.infra.logging import configure_logging
from roadmind.infra.repository import OptimisticLockError, WorkOrderNotFound
from roadmind.mcp.client import RemoteToolError
from roadmind.settings import get_settings

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def assistant_from_request(request: Request) -> EnterpriseAssistantService:
    return request.app.state.enterprise_assistant


Assistant = Annotated[EnterpriseAssistantService, Depends(assistant_from_request)]


def create_assistant_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.roadmind_log_level)
    container = build_container(settings)
    service = RoadMindService(container)
    assistant = build_assistant_service(settings, container.gateway, service)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        close_gateway = getattr(container.gateway, "close", None)
        if close_gateway:
            close_gateway()

    app = FastAPI(
        title="RoadMind Enterprise Assistant Harness",
        version="0.1.0",
        description="Deep Agents runtime isolated from deterministic business services.",
        lifespan=lifespan,
    )
    app.state.enterprise_assistant = assistant
    app.state.roadmind = service
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "roadmind-enterprise-assistant",
            "mode": "deep_agents" if settings.use_deep_agents else "deterministic",
        }

    @app.post("/v1/chat", response_model=AssistantChatResponse)
    def chat(
        payload: AssistantChatRequest,
        principal: CurrentPrincipal,
        assistant_service: Assistant,
    ) -> AssistantChatResponse:
        return assistant_service.chat(payload, principal)

    @app.get("/v1/conversations/{conversation_id}", response_model=ConversationView)
    def conversation(
        conversation_id: str,
        principal: CurrentPrincipal,
        assistant_service: Assistant,
    ) -> ConversationView:
        return assistant_service.conversation(conversation_id, principal)

    @app.exception_handler(PermissionDenied)
    async def forbidden(_: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"error": "permission_denied", "detail": str(exc)},
        )

    @app.exception_handler(ConversationNotFound)
    async def conversation_not_found(_: Request, exc: ConversationNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "conversation_not_found", "detail": str(exc)},
        )

    @app.exception_handler(WorkOrderNotFound)
    async def work_order_not_found(_: Request, exc: WorkOrderNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "work_order_not_found", "detail": str(exc)},
        )

    @app.exception_handler(InvalidTransition)
    async def invalid_transition(_: Request, exc: InvalidTransition) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": "invalid_transition", "detail": str(exc)},
        )

    @app.exception_handler(OptimisticLockError)
    async def optimistic_lock(_: Request, exc: OptimisticLockError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": "optimistic_lock", "detail": str(exc)},
        )

    @app.exception_handler(RemoteToolError)
    async def remote_tool_error(_: Request, exc: RemoteToolError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"error": "mcp_gateway_unavailable", "detail": str(exc)},
        )

    @app.exception_handler(ValueError)
    async def business_rule(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "business_rule", "detail": str(exc)},
        )

    return app


app = create_assistant_app()
