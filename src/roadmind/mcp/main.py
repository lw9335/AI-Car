from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import Redis

from roadmind.agents.dispatch import DispatchAgent, ResourceLeaseBook
from roadmind.agents.parts import PartsAgent
from roadmind.domain.auth import PermissionDenied
from roadmind.infra.db import create_db_engine, create_session_factory, run_migrations
from roadmind.infra.logging import configure_logging
from roadmind.infra.observability import TraceRecorder
from roadmind.infra.redis_leases import RedisResourceLeaseBook
from roadmind.infra.repository import InMemoryWorkOrderRepository, PostgresWorkOrderRepository
from roadmind.mcp.gateway import McpGateway
from roadmind.mcp.http import router
from roadmind.mcp.tools import build_gateway
from roadmind.settings import Settings, get_settings


def build_mcp_gateway(settings: Settings) -> McpGateway:
    traces = TraceRecorder()
    if settings.use_postgres:
        assert settings.database_url is not None
        engine = create_db_engine(settings.database_url)
        run_migrations(engine)
        repo = PostgresWorkOrderRepository(create_session_factory(engine))
    else:
        repo = InMemoryWorkOrderRepository()

    if settings.use_redis:
        assert settings.redis_url is not None
        redis = Redis.from_url(settings.redis_url, decode_responses=False)
        lease_book: Any = RedisResourceLeaseBook(redis)
    else:
        lease_book = ResourceLeaseBook()

    dispatch = DispatchAgent(lease_book=lease_book)
    parts = PartsAgent()
    return build_gateway(traces, repo, dispatch, parts)


def create_mcp_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.roadmind_log_level)
    gateway = build_mcp_gateway(settings)
    app = FastAPI(
        title="RoadMind MCP Gateway",
        version="0.1.0",
        description="Independent MCP policy and tool execution boundary for RoadMind.",
        docs_url="/mcp/docs",
        openapi_url="/mcp/openapi.json",
    )
    app.state.settings = settings
    app.state.tool_gateway = gateway
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(PermissionDenied)
    async def forbidden(_: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"error": "permission_denied", "detail": str(exc)},
        )

    return app


app = create_mcp_app()
