from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from roadmind.api.routes import router
from roadmind.application.service import RoadMindService
from roadmind.domain.auth import PermissionDenied
from roadmind.domain.state_machine import InvalidTransition
from roadmind.infra.repository import OptimisticLockError, WorkOrderNotFound
from roadmind.mcp.gateway import CircuitOpen, RateLimitExceeded, ToolNotFound


def create_app() -> FastAPI:
    app = FastAPI(
        title="RoadMind AI 商用车售后服务协同平台",
        version="0.1.0",
        description=(
            "Evidence-first multi-agent orchestration for commercial-vehicle after-sales service."
        ),
    )
    app.state.roadmind = RoadMindService()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(WorkOrderNotFound)
    async def not_found(_: Request, exc: WorkOrderNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"error": "work_order_not_found", "detail": str(exc)}
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

    @app.exception_handler(ValueError)
    async def business_rule(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "business_rule", "detail": str(exc)})

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


app = create_app()
