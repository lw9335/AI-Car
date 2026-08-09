from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from roadmind.domain.auth import PermissionDenied, Principal
from roadmind.mcp.gateway import (
    CircuitOpen,
    RateLimitExceeded,
    ToolGateway,
    ToolNotFound,
    ToolValidationError,
)

PROTOCOL_VERSION = "2026-07-28"
PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_META = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"


@dataclass(frozen=True)
class McpResponse:
    status_code: int
    body: dict[str, Any] | None


class McpProtocolHandler:
    """Stateless MCP 2026-07-28 JSON-RPC adapter over a ToolGateway port."""

    def __init__(self, gateway: ToolGateway) -> None:
        self._gateway = gateway

    def handle(
        self,
        payload: dict[str, Any],
        *,
        principal: Principal,
        protocol_version: str | None,
        mcp_method: str | None,
        mcp_name: str | None,
    ) -> McpResponse:
        request_id = payload.get("id")
        method = payload.get("method")
        if payload.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self._error(request_id, -32600, "Invalid JSON-RPC request", status_code=400)

        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return self._error(request_id, -32602, "Request params must be an object")

        meta = params.get("_meta") or {}
        body_version = meta.get(PROTOCOL_VERSION_META) if isinstance(meta, dict) else None
        requested_version = protocol_version or body_version
        if requested_version != PROTOCOL_VERSION or body_version != PROTOCOL_VERSION:
            return self._error(
                request_id,
                -32022,
                "Unsupported protocol version",
                data={"supported": [PROTOCOL_VERSION], "requested": requested_version},
                status_code=400,
            )
        if not isinstance(meta.get(CLIENT_INFO_META), dict) or not isinstance(
            meta.get(CLIENT_CAPABILITIES_META), dict
        ):
            return self._error(
                request_id,
                -32600,
                "MCP client metadata is required on every request",
                status_code=400,
            )
        if mcp_method != method:
            return self._error(
                request_id,
                -32600,
                "Mcp-Method header does not match the request method",
                status_code=400,
            )
        if "id" not in payload:
            return McpResponse(status_code=202, body=None)

        if method == "server/discover":
            return self._result(
                request_id,
                {
                    "resultType": "complete",
                    "supportedVersions": [PROTOCOL_VERSION],
                    "capabilities": {"tools": {}},
                    "_meta": {
                        "io.modelcontextprotocol/serverInfo": {
                            "name": "roadmind-mcp-gateway",
                            "version": "0.1.0",
                        }
                    },
                    "instructions": (
                        "Commercial-vehicle service tools. Sensitive writes remain subject "
                        "to RoadMind RBAC and human approval gates."
                    ),
                    "ttlMs": 300_000,
                    "cacheScope": "private",
                },
            )
        if method == "tools/list":
            return self._result(
                request_id,
                {
                    "resultType": "complete",
                    "tools": [
                        self._present_tool(item) for item in self._gateway.list_tools(principal)
                    ],
                    "ttlMs": 60_000,
                    "cacheScope": "private",
                },
            )
        if method == "tools/call":
            return self._call_tool(request_id, params, principal, mcp_name)
        return self._error(request_id, -32601, f"Method not found: {method}")

    def _call_tool(
        self,
        request_id: Any,
        params: dict[str, Any],
        principal: Principal,
        mcp_name: str | None,
    ) -> McpResponse:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return self._error(request_id, -32602, "Tool name and arguments are required")
        if mcp_name != name:
            return self._error(
                request_id,
                -32600,
                "Mcp-Name header does not match the requested tool",
                status_code=400,
            )
        meta = params.get("_meta") or {}
        service_request_id = str(
            arguments.get("service_request_id")
            or meta.get("io.roadmind/serviceRequestId")
            or f"mcp:{request_id}"
        )
        try:
            result = self._gateway.invoke(
                name,
                arguments,
                principal=principal,
                service_request_id=service_request_id,
            )
        except (ToolNotFound, ToolValidationError) as exc:
            return self._error(request_id, -32602, str(exc))
        except PermissionDenied as exc:
            return self._error(request_id, -32001, str(exc), status_code=403)
        except Exception as exc:
            error_type = "upstream_error"
            if isinstance(exc, RateLimitExceeded):
                error_type = "rate_limit_exceeded"
            elif isinstance(exc, CircuitOpen):
                error_type = "circuit_open"
            elif isinstance(exc, ValueError):
                error_type = "business_rule"
            return self._result(
                request_id,
                {
                    "resultType": "complete",
                    "content": [{"type": "text", "text": str(exc)}],
                    "structuredContent": {
                        "error": error_type,
                        "detail": str(exc),
                    },
                    "isError": True,
                },
            )

        serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        return self._result(
            request_id,
            {
                "resultType": "complete",
                "content": [{"type": "text", "text": serialized}],
                "structuredContent": result,
                "isError": False,
            },
        )

    @staticmethod
    def _present_tool(tool: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": tool["name"],
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
            "annotations": tool["annotations"],
        }

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> McpResponse:
        return McpResponse(
            status_code=200,
            body={"jsonrpc": "2.0", "id": request_id, "result": result},
        )

    @staticmethod
    def _error(
        request_id: Any,
        code: int,
        message: str,
        *,
        data: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> McpResponse:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return McpResponse(
            status_code=status_code,
            body={"jsonrpc": "2.0", "id": request_id, "error": error},
        )
