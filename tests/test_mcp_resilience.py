from __future__ import annotations

import pytest

from roadmind.domain.auth import Principal
from roadmind.domain.models import Role
from roadmind.infra.observability import TraceRecorder
from roadmind.mcp.gateway import CircuitOpen, McpGateway, RateLimitExceeded, ToolSpec


def test_gateway_rate_limit_is_enforced_per_actor():
    gateway = McpGateway(TraceRecorder(), requests_per_minute=1)
    gateway.register(ToolSpec("demo.read", "workorder:read", lambda args: args))
    principal = Principal(user_id="same-actor", role=Role.ADMIN)

    gateway.invoke("demo.read", {}, principal=principal, service_request_id="sr-1")

    with pytest.raises(RateLimitExceeded):
        gateway.invoke("demo.read", {}, principal=principal, service_request_id="sr-1")


def test_gateway_opens_circuit_after_three_tool_failures():
    gateway = McpGateway(TraceRecorder())

    def fail(_: dict):
        raise RuntimeError("adapter unavailable")

    gateway.register(ToolSpec("demo.fail", "workorder:read", fail))
    principal = Principal(user_id="operator", role=Role.ADMIN)

    for _ in range(3):
        with pytest.raises(RuntimeError, match="adapter unavailable"):
            gateway.invoke("demo.fail", {}, principal=principal, service_request_id="sr-1")

    with pytest.raises(CircuitOpen):
        gateway.invoke("demo.fail", {}, principal=principal, service_request_id="sr-1")
    assert [record["status"] for record in gateway.audit_log()] == ["error"] * 3


def test_gateway_recursively_redacts_sensitive_audit_arguments():
    gateway = McpGateway(TraceRecorder())
    gateway.register(ToolSpec("demo.write", "workorder:read", lambda args: {"ok": True}))
    principal = Principal(user_id="operator", role=Role.ADMIN)

    gateway.invoke(
        "demo.write",
        {"profile": {"phone": "13900000000"}, "items": [{"approval_token": "secret"}]},
        principal=principal,
        service_request_id="sr-1",
    )

    audit_text = str(gateway.audit_log())
    assert "13900000000" not in audit_text
    assert "secret" not in audit_text
