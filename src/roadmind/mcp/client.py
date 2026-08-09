from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import httpx
import jwt

from roadmind.domain.auth import PermissionDenied, Principal
from roadmind.mcp.gateway import CircuitOpen, RateLimitExceeded, ToolValidationError
from roadmind.mcp.protocol import (
    CLIENT_CAPABILITIES_META,
    CLIENT_INFO_META,
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_META,
)


class RemoteToolError(RuntimeError):
    pass


class RemoteMcpGateway:
    """ToolGateway adapter that talks to an independently deployed MCP service."""

    def __init__(
        self,
        endpoint: str,
        *,
        jwt_secret: str,
        timeout_seconds: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._audit_endpoint = urljoin(endpoint, "management/tool-audit")
        self._jwt_secret = jwt_secret
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        principal: Principal,
        service_request_id: str,
    ) -> dict[str, Any]:
        result = self._request(
            "tools/call",
            principal,
            name=tool_name,
            params={"name": tool_name, "arguments": arguments},
            service_request_id=service_request_id,
        )
        if result.get("isError"):
            structured = result.get("structuredContent") or {}
            content = result.get("content") or []
            detail = content[0].get("text", "remote MCP tool failed") if content else ""
            error_type = structured.get("error") if isinstance(structured, dict) else None
            if error_type == "rate_limit_exceeded":
                raise RateLimitExceeded(principal.user_id)
            if error_type == "circuit_open":
                raise CircuitOpen(tool_name)
            if error_type == "business_rule":
                raise ValueError(detail)
            raise RemoteToolError(detail)
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise RemoteToolError("remote MCP tool returned no structured content")
        return structured

    def list_tools(self, principal: Principal | None = None) -> list[dict[str, Any]]:
        if principal is None:
            raise PermissionDenied("remote MCP tool discovery requires a principal")
        result = self._request("tools/list", principal, params={})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise RemoteToolError("remote MCP server returned an invalid tool catalog")
        return tools

    def audit_log(self, principal: Principal | None = None) -> list[dict[str, Any]]:
        if principal is None:
            raise PermissionDenied("remote MCP audit access requires a principal")
        try:
            response = self._client.get(
                self._audit_endpoint,
                headers={"Authorization": f"Bearer {self._token(principal)}"},
            )
            response.raise_for_status()
            records = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RemoteToolError("remote MCP audit endpoint unavailable") from exc
        if not isinstance(records, list):
            raise RemoteToolError("remote MCP audit endpoint returned invalid data")
        return records

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        principal: Principal,
        *,
        params: dict[str, Any],
        name: str | None = None,
        service_request_id: str | None = None,
    ) -> dict[str, Any]:
        request_id = f"roadmind-{uuid4().hex}"
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": {**params, "_meta": self._metadata(service_request_id)},
        }
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._token(principal)}",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Mcp-Method": method,
        }
        if name:
            headers["Mcp-Name"] = name
        try:
            response = self._client.post(self._endpoint, json=payload, headers=headers)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RemoteToolError("remote MCP gateway unavailable") from exc

        error = body.get("error") if isinstance(body, dict) else None
        if error:
            code = error.get("code")
            message = str(error.get("message") or "remote MCP protocol error")
            if code == -32001 or response.status_code == 403:
                raise PermissionDenied(message)
            if code == -32602:
                raise ToolValidationError(message)
            raise RemoteToolError(message)
        if response.is_error:
            raise RemoteToolError(f"remote MCP gateway returned HTTP {response.status_code}")
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            raise RemoteToolError("remote MCP gateway returned an invalid JSON-RPC result")
        return result

    def _token(self, principal: Principal) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": principal.user_id,
                "role": principal.role.value,
                "region": principal.region,
                "iat": now,
                "exp": now + timedelta(minutes=2),
                "service": "roadmind-api",
            },
            self._jwt_secret,
            algorithm="HS256",
        )

    @staticmethod
    def _metadata(service_request_id: str | None = None) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            PROTOCOL_VERSION_META: PROTOCOL_VERSION,
            CLIENT_INFO_META: {"name": "roadmind-api", "version": "0.1.0"},
            CLIENT_CAPABILITIES_META: {},
        }
        if service_request_id:
            metadata["io.roadmind/serviceRequestId"] = service_request_id
        return metadata
