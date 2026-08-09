from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from roadmind.application.service import RoadMindService
from roadmind.auth.users import decode_access_token
from roadmind.bootstrap import build_container
from roadmind.domain.auth import Principal
from roadmind.domain.models import Role
from roadmind.mcp.client import RemoteMcpGateway
from roadmind.mcp.gateway import CircuitOpen, RateLimitExceeded
from roadmind.mcp.protocol import PROTOCOL_VERSION
from roadmind.mcp.tools import GatewayRoadMindTools
from roadmind.settings import Settings, get_settings


def _headers(role: str, method: str, name: str | None = None) -> dict[str, str]:
    headers = {
        "X-Role": role,
        "X-User-Id": f"mcp-{role}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name:
        headers["Mcp-Name"] = name
    return headers


def _request(request_id: int, method: str, **params: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {
            **params,
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientInfo": {
                    "name": "roadmind-tests",
                    "version": "1.0.0",
                },
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }


def test_mcp_discovery_and_scope_filtered_tool_catalog(mcp_client):
    discovered = mcp_client.post(
        "/mcp",
        json=_request(1, "server/discover"),
        headers=_headers("parts_manager", "server/discover"),
    )
    assert discovered.status_code == 200
    assert discovered.json()["result"]["supportedVersions"] == [PROTOCOL_VERSION]

    listed = mcp_client.post(
        "/mcp",
        json=_request(2, "tools/list"),
        headers=_headers("parts_manager", "tools/list"),
    )
    assert listed.status_code == 200
    tools = listed.json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert "inventory.reserve" in names
    assert "workflow.assign_resource" not in names
    assert all("inputSchema" in tool for tool in tools)


def test_mcp_tool_call_returns_structured_content(mcp_client):
    response = mcp_client.post(
        "/mcp",
        json=_request(3, "tools/call", name="vehicle.decode_vin", arguments={"vin": "abc12345"}),
        headers=_headers("admin", "tools/call", "vehicle.decode_vin"),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["resultType"] == "complete"
    assert result["structuredContent"]["vin"] == "ABC12345"
    assert result["isError"] is False


def test_mcp_rejects_header_body_routing_mismatch(mcp_client):
    response = mcp_client.post(
        "/mcp",
        json=_request(4, "tools/list"),
        headers=_headers("admin", "tools/call"),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600


def test_business_api_does_not_host_mcp_protocol(client):
    response = client.post(
        "/mcp",
        json=_request(5, "tools/list"),
        headers=_headers("admin", "tools/list"),
    )

    assert response.status_code == 404


def test_remote_gateway_forwards_identity_and_correlation_metadata():
    secret = "test-remote-mcp-secret-with-32-chars"
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": captured["payload"]["id"],
                "result": {
                    "resultType": "complete",
                    "content": [{"type": "text", "text": '{"valid":true}'}],
                    "structuredContent": {"valid": True},
                    "isError": False,
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway = RemoteMcpGateway(
        "http://mcp-gateway:8001/mcp",
        jwt_secret=secret,
        client=client,
    )
    principal = Principal(user_id="api-user", role=Role.ADMIN, region="south_china")

    result = gateway.invoke(
        "vehicle.decode_vin",
        {"vin": "ABC12345"},
        principal=principal,
        service_request_id="sr-correlation",
    )

    token = captured["authorization"].removeprefix("Bearer ")
    claims = decode_access_token(token, secret=secret)
    assert result == {"valid": True}
    assert claims["sub"] == "api-user"
    assert claims["role"] == "admin"
    metadata = captured["payload"]["params"]["_meta"]
    assert metadata["io.roadmind/serviceRequestId"] == "sr-correlation"
    gateway.close()


def test_remote_gateway_interoperates_with_independent_mcp_app(mcp_client):
    def bridge(request: httpx.Request) -> httpx.Response:
        response = mcp_client.request(
            request.method,
            request.url.path,
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers={"content-type": response.headers.get("content-type", "application/json")},
        )

    gateway = RemoteMcpGateway(
        "http://mcp-gateway:8001/mcp",
        jwt_secret=get_settings().jwt_secret,
        client=httpx.Client(transport=httpx.MockTransport(bridge)),
    )
    principal = Principal(user_id="api-admin", role=Role.ADMIN)

    result = gateway.invoke(
        "vehicle.decode_vin",
        {"vin": "abc12345"},
        principal=principal,
        service_request_id="sr-e2e",
    )

    assert result["vin"] == "ABC12345"
    assert result["valid"] is True
    stock = GatewayRoadMindTools(gateway).inventory_snapshot("sr-e2e", principal)
    assert stock["NOX-SENSOR-AU-02"] > 0
    assert any(record["tool"] == "vehicle.decode_vin" for record in gateway.audit_log(principal))
    gateway.close()


@pytest.mark.parametrize(
    ("error_type", "expected_exception"),
    [
        ("rate_limit_exceeded", RateLimitExceeded),
        ("circuit_open", CircuitOpen),
        ("business_rule", ValueError),
    ],
)
def test_remote_gateway_preserves_tool_error_semantics(error_type, expected_exception):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "resultType": "complete",
                    "content": [{"type": "text", "text": "tool failed"}],
                    "structuredContent": {"error": error_type, "detail": "tool failed"},
                    "isError": True,
                },
            },
        )

    gateway = RemoteMcpGateway(
        "http://mcp-gateway:8001/mcp",
        jwt_secret="test-remote-mcp-secret-with-32-chars",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(expected_exception):
        gateway.invoke(
            "demo.tool",
            {},
            principal=Principal(user_id="admin", role=Role.ADMIN),
            service_request_id="sr-error",
        )
    gateway.close()


def test_factory_can_select_remote_mcp_gateway():
    settings = Settings(
        roadmind_env="local",
        mcp_gateway_url="http://mcp-gateway:8001/mcp",
    )
    container = build_container(settings, use_remote_gateway=True)

    assert isinstance(container.gateway, RemoteMcpGateway)
    container.gateway.close()


def test_service_reuses_gateway_built_by_composition_root():
    container = build_container()
    service = RoadMindService(container)

    assert service.gateway is container.gateway
    assert service.tools is container.tools
