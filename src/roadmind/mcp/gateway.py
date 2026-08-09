from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Protocol

from roadmind.domain.auth import ROLE_SCOPES, Principal, require_scope
from roadmind.infra.observability import TraceRecorder


class ToolNotFound(KeyError):
    pass


class ToolValidationError(ValueError):
    pass


class RateLimitExceeded(RuntimeError):
    pass


class CircuitOpen(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    required_scope: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    required_params: tuple[str, ...] = ()
    risk: str = "read"
    idempotent: bool = True
    description: str = ""
    input_schema: dict[str, Any] | None = None

    def mcp_input_schema(self) -> dict[str, Any]:
        if self.input_schema is not None:
            return self.input_schema
        return {
            "type": "object",
            "properties": {name: {} for name in self.required_params},
            "required": list(self.required_params),
        }


class ToolGateway(Protocol):
    """Application-facing port implemented by local or remote MCP gateways."""

    def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        principal: Principal,
        service_request_id: str,
    ) -> dict[str, Any]: ...

    def list_tools(self, principal: Principal | None = None) -> list[dict[str, Any]]: ...

    def audit_log(self, principal: Principal | None = None) -> list[dict[str, Any]]: ...


class McpGateway:
    """Central auth, validation, rate-limit, circuit-breaker, tracing and audit boundary."""

    def __init__(self, traces: TraceRecorder, *, requests_per_minute: int = 120) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._traces = traces
        self._limit = requests_per_minute
        self._calls: dict[str, deque[datetime]] = defaultdict(deque)
        self._failures: dict[str, int] = defaultdict(int)
        self._circuit_until: dict[str, datetime] = {}
        self._audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        principal: Principal,
        service_request_id: str,
    ) -> dict[str, Any]:
        spec = self._tools.get(tool_name)
        if spec is None:
            raise ToolNotFound(tool_name)
        require_scope(principal, spec.required_scope)
        self._check_rate_limit(principal.user_id)
        self._check_circuit(tool_name)
        self._validate_arguments(spec, arguments)

        record = {
            "tool": tool_name,
            "actor": principal.user_id,
            "role": principal.role,
            "service_request_id": service_request_id,
            "risk": spec.risk,
            "arguments": self._redact(arguments),
            "at": datetime.now(UTC).isoformat(),
        }
        with self._traces.span(
            tool_name,
            "tool",
            service_request_id=service_request_id,
            actor=principal.user_id,
            risk=spec.risk,
        ):
            try:
                result = spec.handler(arguments)
                with self._lock:
                    self._failures[tool_name] = 0
                record["status"] = "ok"
                return result
            except Exception:
                with self._lock:
                    self._failures[tool_name] += 1
                    failure_count = self._failures[tool_name]
                record["status"] = "error"
                if failure_count >= 3:
                    with self._lock:
                        self._circuit_until[tool_name] = datetime.now(UTC) + timedelta(seconds=30)
                raise
            finally:
                with self._lock:
                    self._audit.append(record)

    def list_tools(self, principal: Principal | None = None) -> list[dict[str, Any]]:
        tools = [
            {
                "name": spec.name,
                "description": spec.description or spec.name,
                "inputSchema": spec.mcp_input_schema(),
                "required_scope": spec.required_scope,
                "risk": spec.risk,
                "idempotent": spec.idempotent,
                "annotations": {
                    "readOnlyHint": spec.risk == "read",
                    "destructiveHint": spec.risk == "destructive_write",
                    "idempotentHint": spec.idempotent,
                },
            }
            for spec in self._tools.values()
            if principal is None or self._has_scope(principal, spec.required_scope)
        ]
        return sorted(tools, key=lambda item: item["name"])

    def audit_log(self, principal: Principal | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._audit)

    def _check_rate_limit(self, user_id: str) -> None:
        now = datetime.now(UTC)
        with self._lock:
            window = self._calls[user_id]
            while window and now - window[0] > timedelta(minutes=1):
                window.popleft()
            if len(window) >= self._limit:
                raise RateLimitExceeded(user_id)
            window.append(now)

    def _check_circuit(self, tool_name: str) -> None:
        with self._lock:
            until = self._circuit_until.get(tool_name)
        if until and until > datetime.now(UTC):
            raise CircuitOpen(tool_name)

    @staticmethod
    def _has_scope(principal: Principal, scope: str) -> bool:
        scopes = ROLE_SCOPES[principal.role]
        return "*" in scopes or scope in scopes

    @staticmethod
    def _validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> None:
        schema = spec.mcp_input_schema()
        required = schema.get("required", spec.required_params)
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ToolValidationError(f"missing required params: {missing}")

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unexpected = sorted(set(arguments) - set(properties))
            if unexpected:
                raise ToolValidationError(f"unexpected params: {unexpected}")

        type_map: dict[str, tuple[type, ...]] = {
            "array": (list,),
            "boolean": (bool,),
            "integer": (int,),
            "number": (int, float),
            "object": (dict,),
            "string": (str,),
        }
        for name, value in arguments.items():
            property_schema = properties.get(name, {})
            expected_name = property_schema.get("type")
            expected = type_map.get(expected_name)
            boolean_number = expected_name in {"integer", "number"} and isinstance(value, bool)
            if expected and (not isinstance(value, expected) or boolean_number):
                raise ToolValidationError(f"param {name!r} must be {expected_name}")
            if expected_name == "array" and isinstance(value, list):
                item_name = property_schema.get("items", {}).get("type")
                item_type = type_map.get(item_name)
                if item_type and any(not isinstance(item, item_type) for item in value):
                    raise ToolValidationError(f"items in param {name!r} must be {item_name}")

    @staticmethod
    def _redact(arguments: dict[str, Any]) -> dict[str, Any]:
        sensitive = {"phone", "token", "approval_token", "password"}

        def scrub(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: "***" if key.lower() in sensitive else scrub(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [scrub(item) for item in value]
            return value

        return scrub(arguments)
