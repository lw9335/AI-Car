from __future__ import annotations

from typing import Any

from roadmind.agents.dispatch import DispatchAgent
from roadmind.agents.parts import PartsAgent
from roadmind.infra.observability import TraceRecorder
from roadmind.infra.repository import InMemoryWorkOrderRepository
from roadmind.mcp.gateway import McpGateway, ToolSpec


def build_gateway(
    traces: TraceRecorder,
    repo: InMemoryWorkOrderRepository,
    dispatch: DispatchAgent,
    parts: PartsAgent,
) -> McpGateway:
    gateway = McpGateway(traces)

    def vehicle_decode(args: dict[str, Any]) -> dict[str, Any]:
        vin = str(args["vin"]).upper()
        return {"vin": vin, "valid": 8 <= len(vin) <= 32, "source": "mock_dms_adapter"}

    def workorder_history(args: dict[str, Any]) -> dict[str, Any]:
        order = repo.get(str(args["service_request_id"]))
        return {"timeline": [event.model_dump(mode="json") for event in order.timeline]}

    def live_signals(args: dict[str, Any]) -> dict[str, Any]:
        order = repo.get(str(args["service_request_id"]))
        return {"signals": order.telemetry, "freshness_seconds": 5, "source": "mock_iot_adapter"}

    def assign_resource(args: dict[str, Any]) -> dict[str, Any]:
        order_id = str(args["service_request_id"])
        resource_id = str(args["resource_id"])
        order = repo.get(order_id)
        dispatch.reserve(order, resource_id)
        return {"reservation": "held", "resource_id": resource_id, "ttl_seconds": 120}

    def inventory_reserve(args: dict[str, Any]) -> dict[str, Any]:
        order_id = str(args["service_request_id"])
        codes = list(args["part_codes"])
        parts.reserve(order_id, codes)
        return {"reservation": "held", "part_codes": codes}

    def inventory_release(args: dict[str, Any]) -> dict[str, Any]:
        codes = parts.release(str(args["service_request_id"]))
        return {"released": codes}

    specs = [
        ToolSpec("vehicle.decode_vin", "workorder:create", vehicle_decode, ("vin",)),
        ToolSpec("vehicle.get_profile", "workorder:read", lambda a: {"vin": a["vin"]}, ("vin",)),
        ToolSpec(
            "workorder.get_history", "workorder:read", workorder_history, ("service_request_id",)
        ),
        ToolSpec(
            "telemetry.get_live_signals", "workorder:read", live_signals, ("service_request_id",)
        ),
        ToolSpec(
            "dtc.get_definition",
            "diagnosis:run",
            lambda a: {"dtc": a["dtc"], "source": "oem"},
            ("dtc",),
        ),
        ToolSpec(
            "knowledge.search_manual",
            "diagnosis:run",
            lambda a: {"query": a["query"], "adapter": "hybrid_rag"},
            ("query",),
        ),
        ToolSpec(
            "knowledge.search_case",
            "diagnosis:run",
            lambda a: {"query": a["query"], "adapter": "case_index"},
            ("query",),
        ),
        ToolSpec(
            "expert.request_review",
            "diagnosis:run",
            lambda a: {"queued": True},
            ("service_request_id",),
            risk="write",
            idempotent=False,
        ),
        ToolSpec(
            "workflow.assign_resource",
            "dispatch:approve",
            assign_resource,
            ("service_request_id", "resource_id"),
            risk="sensitive_write",
            idempotent=False,
        ),
        ToolSpec("inventory.search_available", "parts:read", lambda a: {"stock": parts.snapshot()}),
        ToolSpec(
            "inventory.reserve",
            "parts:reserve",
            inventory_reserve,
            ("service_request_id", "part_codes"),
            risk="sensitive_write",
            idempotent=True,
        ),
        ToolSpec(
            "inventory.release",
            "parts:reserve",
            inventory_release,
            ("service_request_id",),
            risk="write",
        ),
        ToolSpec(
            "pricing.calculate_quote",
            "parts:read",
            lambda a: {"currency": "CNY", "status": "quoted"},
        ),
        ToolSpec(
            "map.calculate_eta",
            "dispatch:read",
            lambda a: {"eta_minutes": 35, "source": "mock_map_adapter"},
        ),
        ToolSpec(
            "notification.send",
            "workorder:read",
            lambda a: {"accepted": True},
            risk="write",
            idempotent=False,
        ),
        ToolSpec(
            "metrics.run_template",
            "metrics:query",
            lambda a: {"metric_id": a["metric_id"], "status": "routed"},
            ("metric_id",),
        ),
        ToolSpec(
            "case.create_candidate",
            "service:execute",
            lambda a: {"status": "quarantine_pending_quality_review"},
            risk="write",
        ),
    ]
    for spec in specs:
        gateway.register(spec)
    return gateway
