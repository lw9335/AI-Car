from __future__ import annotations

import logging

from redis import Redis

from roadmind.agents.diagnosis import DiagnosisAgent
from roadmind.agents.dispatch import DispatchAgent, ResourceLeaseBook
from roadmind.agents.operations import OperationsAgent
from roadmind.agents.parts import PartsAgent
from roadmind.application.ports import (
    DiagnosisCapability,
    DispatchCapability,
    OperationsCapability,
    PartsCapability,
    ResourceLease,
)
from roadmind.auth.users import InMemoryUserStore, PostgresUserStore, UserStore
from roadmind.infra.db import create_db_engine, create_session_factory, run_migrations
from roadmind.infra.observability import TraceRecorder
from roadmind.infra.outbox import OutboxStore, PostgresTransactionalOutbox, TransactionalOutbox
from roadmind.infra.pii_vault import PiiStore, PiiVault, PostgresPiiVault
from roadmind.infra.redis_leases import RedisResourceLeaseBook
from roadmind.infra.repository import (
    InMemoryWorkOrderRepository,
    PostgresWorkOrderRepository,
    WorkOrderRepository,
)
from roadmind.mcp.client import RemoteMcpGateway
from roadmind.mcp.gateway import ToolGateway
from roadmind.mcp.tools import GatewayRoadMindTools, RoadMindToolPort, build_gateway
from roadmind.settings import Settings, get_settings
from roadmind.workflows.task_planner import WorkOrderPlanner, build_work_order_planner

logger = logging.getLogger(__name__)


class AppContainer:
    """Runtime dependencies selected by deployable entrypoints, outside the application layer."""

    def __init__(
        self,
        *,
        settings: Settings,
        repo: WorkOrderRepository,
        vault: PiiStore,
        outbox: OutboxStore,
        lease_book: ResourceLease,
        planner: WorkOrderPlanner,
        users: UserStore,
        traces: TraceRecorder | None = None,
        gateway: ToolGateway | None = None,
        tools: RoadMindToolPort | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.vault = vault
        self.outbox = outbox
        self.lease_book = lease_book
        self.planner = planner
        self.users = users
        self.traces = traces or TraceRecorder()
        self.diagnosis_service: DiagnosisCapability = DiagnosisAgent()
        self.dispatch_service: DispatchCapability = DispatchAgent(lease_book=self.lease_book)
        self.parts_service: PartsCapability = PartsAgent()
        self.operations_service: OperationsCapability = OperationsAgent()
        # Compatibility aliases for callers using the original attribute names.
        self.diagnosis = self.diagnosis_service
        self.dispatch = self.dispatch_service
        self.parts = self.parts_service
        self.operations = self.operations_service
        self.gateway = gateway or build_gateway(
            self.traces, self.repo, self.dispatch_service, self.parts_service
        )
        self.tools = tools or GatewayRoadMindTools(self.gateway)


def build_container(
    settings: Settings | None = None,
    *,
    use_remote_gateway: bool | None = None,
) -> AppContainer:
    settings = settings or get_settings()
    planner = build_work_order_planner(settings)
    if settings.use_postgres:
        if settings.database_url is None:
            raise ValueError("DATABASE_URL is required when PostgreSQL is enabled")
        engine = create_db_engine(settings.database_url)
        run_migrations(engine)
        sessions = create_session_factory(engine)
        repo: WorkOrderRepository = PostgresWorkOrderRepository(sessions)
        vault: PiiStore = PostgresPiiVault(sessions)
        outbox: OutboxStore = PostgresTransactionalOutbox(sessions)
        users: UserStore = PostgresUserStore(sessions)
        users.ensure_seed_users(settings.demo_password)
        logger.info("RoadMind adapters: postgres")
    else:
        repo = InMemoryWorkOrderRepository()
        vault = PiiVault()
        outbox = TransactionalOutbox()
        users = InMemoryUserStore()
        users.ensure_seed_users(settings.demo_password)
        logger.info("RoadMind adapters: memory")

    if settings.use_redis:
        if settings.redis_url is None:
            raise ValueError("REDIS_URL is required when Redis is enabled")
        client = Redis.from_url(settings.redis_url, decode_responses=False)
        lease_book: ResourceLease = RedisResourceLeaseBook(client)
        logger.info("RoadMind leases: redis")
    else:
        lease_book = ResourceLeaseBook()
        logger.info("RoadMind leases: memory")

    remote_gateway = settings.use_remote_mcp if use_remote_gateway is None else use_remote_gateway
    gateway: ToolGateway | None = None
    if remote_gateway:
        if not settings.mcp_gateway_url:
            raise ValueError("MCP_GATEWAY_URL is required for the remote MCP gateway")
        gateway = RemoteMcpGateway(
            settings.mcp_gateway_url,
            jwt_secret=settings.jwt_secret,
            timeout_seconds=settings.mcp_request_timeout_seconds,
        )
        logger.info("RoadMind tools: remote MCP gateway %s", settings.mcp_gateway_url)
    else:
        logger.info("RoadMind tools: in-process MCP gateway")

    return AppContainer(
        settings=settings,
        repo=repo,
        vault=vault,
        outbox=outbox,
        lease_book=lease_book,
        planner=planner,
        users=users,
        gateway=gateway,
    )
