from __future__ import annotations

from typing import Any, Protocol

from roadmind.application.ports import DispatchCapability, PartsCapability
from roadmind.domain.auth import Principal
from roadmind.infra.observability import TraceRecorder
from roadmind.infra.repository import WorkOrderRepository
from roadmind.mcp.gateway import McpGateway, ToolGateway, ToolSpec


class RoadMindToolPort(Protocol):
    """Typed use-case port; the application never depends on MCP tool names."""

    def decode_vin(self, vin: str, principal: Principal) -> dict[str, Any]: ...

    def get_live_signals(
        self,
        service_request_id: str,
        signals: dict[str, Any],
        principal: Principal,
    ) -> dict[str, Any]: ...

    def assign_resource(
        self, service_request_id: str, resource_id: str, principal: Principal
    ) -> dict[str, Any]: ...

    def reserve_inventory(
        self, service_request_id: str, part_codes: list[str], principal: Principal
    ) -> dict[str, Any]: ...

    def inventory_snapshot(
        self, service_request_id: str, principal: Principal
    ) -> dict[str, int]: ...

    def release_fulfillment(
        self, service_request_id: str, resource_id: str | None, principal: Principal
    ) -> dict[str, Any]: ...


class GatewayRoadMindTools:
    """Typed facade over the generic MCP gateway port."""

    def __init__(self, gateway: ToolGateway) -> None:
        self._gateway = gateway

    def decode_vin(self, vin: str, principal: Principal) -> dict[str, Any]:
        return self._call("vehicle.decode_vin", {"vin": vin}, principal, "pending")

    def get_live_signals(
        self,
        service_request_id: str,
        signals: dict[str, Any],
        principal: Principal,
    ) -> dict[str, Any]:
        return self._call(
            "telemetry.get_live_signals",
            {"service_request_id": service_request_id, "signals": signals},
            principal,
            service_request_id,
        )

    def assign_resource(
        self, service_request_id: str, resource_id: str, principal: Principal
    ) -> dict[str, Any]:
        return self._call(
            "workflow.assign_resource",
            {"service_request_id": service_request_id, "resource_id": resource_id},
            principal,
            service_request_id,
        )

    def reserve_inventory(
        self, service_request_id: str, part_codes: list[str], principal: Principal
    ) -> dict[str, Any]:
        return self._call(
            "inventory.reserve",
            {"service_request_id": service_request_id, "part_codes": part_codes},
            principal,
            service_request_id,
        )

    def inventory_snapshot(self, service_request_id: str, principal: Principal) -> dict[str, int]:
        result = self._call(
            "inventory.search_available",
            {},
            principal,
            service_request_id,
        )
        return {str(code): int(stock) for code, stock in result["stock"].items()}

    def release_fulfillment(
        self, service_request_id: str, resource_id: str | None, principal: Principal
    ) -> dict[str, Any]:
        released_resource = None
        if resource_id:
            result = self._call(
                "workflow.release_resource",
                {"service_request_id": service_request_id, "resource_id": resource_id},
                principal,
                service_request_id,
            )
            released_resource = result["released_resource"]
        parts = self._call(
            "inventory.release",
            {"service_request_id": service_request_id},
            principal,
            service_request_id,
        )
        return {"released_resource": released_resource, "released_parts": parts["released"]}

    def _call(
        self,
        name: str,
        arguments: dict[str, Any],
        principal: Principal,
        service_request_id: str,
    ) -> dict[str, Any]:
        return self._gateway.invoke(
            name,
            arguments,
            principal=principal,
            service_request_id=service_request_id,
        )


def _schema(properties: dict[str, str], required: tuple[str, ...] = ()) -> dict[str, Any]:
    definitions = {name: {"type": kind} for name, kind in properties.items()}
    for definition in definitions.values():
        if definition["type"] == "array":
            definition["items"] = {"type": "string"}
    return {
        "type": "object",
        "properties": definitions,
        "required": list(required),
        "additionalProperties": False,
    }


def build_gateway(
    traces: TraceRecorder,
    repo: WorkOrderRepository,
    dispatch: DispatchCapability,
    parts: PartsCapability,
) -> McpGateway:
    gateway = McpGateway(traces)

    def vehicle_decode(args: dict[str, Any]) -> dict[str, Any]:
        vin = str(args["vin"]).upper()
        return {"vin": vin, "valid": 8 <= len(vin) <= 32, "source": "mock_dms_adapter"}

    def workorder_history(args: dict[str, Any]) -> dict[str, Any]:
        order = repo.get(str(args["service_request_id"]))
        return {"timeline": [event.model_dump(mode="json") for event in order.timeline]}

    def live_signals(args: dict[str, Any]) -> dict[str, Any]:
        signals = args.get("signals")
        if signals is None:
            order = repo.get(str(args["service_request_id"]))
            signals = order.telemetry
        return {
            "signals": signals,
            "freshness_seconds": 5,
            "source": "mock_iot_adapter",
        }

    def assign_resource(args: dict[str, Any]) -> dict[str, Any]:
        order_id = str(args["service_request_id"])
        resource_id = str(args["resource_id"])
        order = repo.get(order_id)
        dispatch.reserve(order, resource_id)
        return {"reservation": "held", "resource_id": resource_id, "ttl_seconds": 120}

    def release_resource(args: dict[str, Any]) -> dict[str, Any]:
        resource_id = str(args["resource_id"])
        order_id = str(args["service_request_id"])
        dispatch.release(resource_id, order_id)
        return {"released_resource": resource_id}

    def inventory_reserve(args: dict[str, Any]) -> dict[str, Any]:
        order_id = str(args["service_request_id"])
        codes = list(args["part_codes"])
        parts.reserve(order_id, codes)
        return {"reservation": "held", "part_codes": codes}

    def inventory_release(args: dict[str, Any]) -> dict[str, Any]:
        codes = parts.release(str(args["service_request_id"]))
        return {"released": codes}

    specs = [
        ToolSpec(
            "vehicle.decode_vin",
            "workorder:create",
            vehicle_decode,
            ("vin",),
            description="Validate and normalize a commercial-vehicle VIN.",
            input_schema=_schema({"vin": "string"}, ("vin",)),
        ),
        ToolSpec(
            "vehicle.get_profile",
            "workorder:read",
            lambda a: {"vin": a["vin"]},
            ("vin",),
            description="Read the vehicle profile associated with a VIN.",
            input_schema=_schema({"vin": "string"}, ("vin",)),
        ),
        ToolSpec(
            "workorder.get_history",
            "workorder:read",
            workorder_history,
            ("service_request_id",),
            description="Read the auditable timeline for a service request.",
            input_schema=_schema({"service_request_id": "string"}, ("service_request_id",)),
        ),
        ToolSpec(
            "telemetry.get_live_signals",
            "workorder:read",
            live_signals,
            ("service_request_id",),
            description="Read recent vehicle telemetry through the IoT adapter.",
            input_schema=_schema(
                {"service_request_id": "string", "signals": "object"},
                ("service_request_id",),
            ),
        ),
        ToolSpec(
            "dtc.get_definition",
            "diagnosis:run",
            lambda a: {"dtc": a["dtc"], "source": "oem"},
            ("dtc",),
            description="Read an OEM diagnostic trouble-code definition.",
            input_schema=_schema({"dtc": "string"}, ("dtc",)),
        ),
        ToolSpec(
            "knowledge.search_manual",
            "diagnosis:run",
            lambda a: {"query": a["query"], "adapter": "hybrid_rag"},
            ("query",),
            description="Search versioned service manuals through Hybrid RAG.",
            input_schema=_schema({"query": "string"}, ("query",)),
        ),
        ToolSpec(
            "knowledge.search_case",
            "diagnosis:run",
            lambda a: {"query": a["query"], "adapter": "case_index"},
            ("query",),
            description="Search quality-approved historical service cases.",
            input_schema=_schema({"query": "string"}, ("query",)),
        ),
        ToolSpec(
            "expert.request_review",
            "diagnosis:run",
            lambda a: {"queued": True},
            ("service_request_id",),
            risk="write",
            idempotent=False,
            description="Queue a diagnosis package for expert review.",
            input_schema=_schema({"service_request_id": "string"}, ("service_request_id",)),
        ),
        ToolSpec(
            "workflow.assign_resource",
            "dispatch:approve",
            assign_resource,
            ("service_request_id", "resource_id"),
            risk="sensitive_write",
            idempotent=False,
            description="Reserve an approved field-service resource.",
            input_schema=_schema(
                {"service_request_id": "string", "resource_id": "string"},
                ("service_request_id", "resource_id"),
            ),
        ),
        ToolSpec(
            "workflow.release_resource",
            "dispatch:approve",
            release_resource,
            ("service_request_id", "resource_id"),
            risk="write",
            description="Compensate a resource reservation for a service request.",
            input_schema=_schema(
                {"service_request_id": "string", "resource_id": "string"},
                ("service_request_id", "resource_id"),
            ),
        ),
        ToolSpec(
            "inventory.search_available",
            "parts:read",
            lambda a: {"stock": parts.snapshot()},
            description="Read available inventory from the WMS adapter.",
            input_schema=_schema({}),
        ),
        ToolSpec(
            "inventory.reserve",
            "parts:reserve",
            inventory_reserve,
            ("service_request_id", "part_codes"),
            risk="sensitive_write",
            idempotent=True,
            description="Reserve VIN-compatible parts for a service request.",
            input_schema=_schema(
                {"service_request_id": "string", "part_codes": "array"},
                ("service_request_id", "part_codes"),
            ),
        ),
        ToolSpec(
            "inventory.release",
            "parts:reserve",
            inventory_release,
            ("service_request_id",),
            risk="write",
            description="Compensate all parts reservations for a service request.",
            input_schema=_schema({"service_request_id": "string"}, ("service_request_id",)),
        ),
        ToolSpec(
            "pricing.calculate_quote",
            "parts:read",
            lambda a: {"currency": "CNY", "status": "quoted"},
            description="Calculate a parts quote through the pricing adapter.",
            input_schema=_schema({}),
        ),
        ToolSpec(
            "map.calculate_eta",
            "dispatch:read",
            lambda a: {"eta_minutes": 35, "source": "mock_map_adapter"},
            description="Calculate a field-service ETA through the map adapter.",
            input_schema=_schema({}),
        ),
        ToolSpec(
            "notification.send",
            "workorder:read",
            lambda a: {"accepted": True},
            risk="write",
            idempotent=False,
            description="Send a service notification through the messaging adapter.",
            input_schema=_schema({}),
        ),
        ToolSpec(
            "metrics.run_template",
            "metrics:query",
            lambda a: {"metric_id": a["metric_id"], "status": "routed"},
            ("metric_id",),
            description="Run an approved, parameterized operations metric template.",
            input_schema=_schema({"metric_id": "string"}, ("metric_id",)),
        ),
        ToolSpec(
            "case.create_candidate",
            "service:execute",
            lambda a: {"status": "quarantine_pending_quality_review"},
            risk="write",
            description="Create a quarantined knowledge-case candidate.",
            input_schema=_schema({}),
        ),
    ]
    for spec in specs:
        gateway.register(spec)
    return gateway
