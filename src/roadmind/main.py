from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from roadmind.api.routes import router
from roadmind.application.service import RoadMindService
from roadmind.assistant.service import build_assistant_service
from roadmind.assistant.store import ConversationNotFound
from roadmind.bootstrap import build_container
from roadmind.domain.auth import PermissionDenied
from roadmind.domain.state_machine import InvalidTransition
from roadmind.infra.logging import configure_logging
from roadmind.infra.repository import OptimisticLockError, WorkOrderNotFound
from roadmind.mcp.client import RemoteToolError
from roadmind.mcp.gateway import CircuitOpen, RateLimitExceeded, ToolNotFound
from roadmind.settings import get_settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_api_credentials()
    configure_logging(settings.roadmind_log_level)
    container = build_container(settings)
    service = RoadMindService(container)
    enterprise_assistant = build_assistant_service(settings, container.gateway, service)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        def _log_publisher(message) -> None:
            logger.info(
                "outbox.delivered topic=%s message_id=%s", message.topic, message.message_id
            )

        try:
            delivered = service.outbox.deliver(_log_publisher)
            if delivered:
                logger.info("outbox relay delivered %s messages on startup", delivered)
        except Exception:
            logger.exception("outbox relay failed on startup")
        yield
        close_gateway = getattr(container.gateway, "close", None)
        if close_gateway:
            close_gateway()

    app = FastAPI(
        title="RoadMind AI 商用车售后服务协同平台",
        version="0.1.0",
        description=(
            "Evidence-first multi-agent orchestration for commercial-vehicle after-sales service."
        ),
        lifespan=lifespan,
    )
    app.state.roadmind = service
    app.state.enterprise_assistant = enterprise_assistant
    app.state.tool_gateway = container.gateway
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(WorkOrderNotFound)
    async def not_found(_: Request, exc: WorkOrderNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"error": "work_order_not_found", "detail": str(exc)}
        )

    @app.exception_handler(ConversationNotFound)
    async def conversation_not_found(_: Request, exc: ConversationNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "conversation_not_found", "detail": str(exc)},
        )

    @app.exception_handler(PermissionDenied)
    async def forbidden(_: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse(
            status_code=403, content={"error": "permission_denied", "detail": str(exc)}
        )

    @app.exception_handler(InvalidTransition)
    async def invalid_transition(_: Request, exc: InvalidTransition) -> JSONResponse:
        return JSONResponse(
            status_code=409, content={"error": "invalid_transition", "detail": str(exc)}
        )

    @app.exception_handler(OptimisticLockError)
    async def optimistic_lock(_: Request, exc: OptimisticLockError) -> JSONResponse:
        return JSONResponse(
            status_code=409, content={"error": "optimistic_lock", "detail": str(exc)}
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limit_exceeded", "detail": str(exc)},
            headers={"Retry-After": "60"},
        )

    @app.exception_handler(CircuitOpen)
    async def circuit_open(_: Request, exc: CircuitOpen) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": "upstream_circuit_open", "detail": str(exc)},
        )

    @app.exception_handler(ToolNotFound)
    async def tool_not_found(_: Request, exc: ToolNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"error": "tool_not_found", "detail": str(exc)}
        )

    @app.exception_handler(RemoteToolError)
    async def remote_tool_error(_: Request, exc: RemoteToolError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"error": "mcp_gateway_unavailable", "detail": str(exc)},
        )

    @app.exception_handler(ValueError)
    async def business_rule(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "business_rule", "detail": str(exc)})

    return app


app = create_app()
