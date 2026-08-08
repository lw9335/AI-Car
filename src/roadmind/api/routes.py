from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from roadmind.api.dependencies import principal_from_headers
from roadmind.application.service import RoadMindService
from roadmind.domain.auth import Principal, require_scope
from roadmind.domain.models import (
    ClosureRequest,
    DiagnosisMismatch,
    DispatchApproval,
    ExpertDecision,
    OpsQuery,
    PartsReservationRequest,
    Role,
    ServiceRequestCreate,
)

router = APIRouter(prefix="/api/v1")
CurrentPrincipal = Annotated[Principal, Depends(principal_from_headers)]


def service_from_request(request: Request) -> RoadMindService:
    return request.app.state.roadmind


Service = Annotated[RoadMindService, Depends(service_from_request)]


def present_order(order: Any, principal: Principal) -> dict[str, Any]:
    data = order.model_dump(mode="json")
    can_view_tokens = principal.role in {Role.DISPATCHER, Role.ADMIN}
    for approval in data["approvals"]:
        if not can_view_tokens:
            approval["token"] = "***"
    return data


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "roadmind", "version": "0.1.0"}


@router.post("/work-orders", status_code=201)
def create_work_order(
    payload: ServiceRequestCreate, principal: CurrentPrincipal, service: Service
) -> dict[str, Any]:
    return present_order(service.create_request(payload, principal), principal)


@router.get("/work-orders")
def list_work_orders(principal: CurrentPrincipal, service: Service) -> list[dict[str, Any]]:
    return [present_order(order, principal) for order in service.list_orders(principal)]


@router.get("/work-orders/{order_id}")
def get_work_order(order_id: str, principal: CurrentPrincipal, service: Service) -> dict[str, Any]:
    return present_order(service.get_order(order_id, principal), principal)


@router.post("/work-orders/{order_id}/diagnose")
def diagnose(order_id: str, principal: CurrentPrincipal, service: Service) -> dict[str, Any]:
    return present_order(service.run_diagnosis(order_id, principal), principal)


@router.post("/work-orders/{order_id}/expert-confirm")
def confirm_diagnosis(
    order_id: str,
    payload: ExpertDecision,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_order(service.confirm_diagnosis(order_id, payload, principal), principal)


@router.post("/work-orders/{order_id}/dispatch/approve")
def approve_dispatch(
    order_id: str,
    payload: DispatchApproval,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_order(service.approve_dispatch(order_id, payload, principal), principal)


@router.post("/work-orders/{order_id}/parts/reserve")
def reserve_parts(
    order_id: str,
    payload: PartsReservationRequest,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_order(service.reserve_parts(order_id, payload, principal), principal)


@router.post("/work-orders/{order_id}/service/start")
def start_service(order_id: str, principal: CurrentPrincipal, service: Service) -> dict[str, Any]:
    return present_order(service.start_service(order_id, principal), principal)


@router.post("/work-orders/{order_id}/mismatch")
def report_mismatch(
    order_id: str,
    payload: DiagnosisMismatch,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_order(service.report_mismatch(order_id, payload, principal), principal)


@router.post("/work-orders/{order_id}/close")
def close_work_order(
    order_id: str,
    payload: ClosureRequest,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_order(service.close_order(order_id, payload, principal), principal)


@router.post("/operations/query")
def query_operations(
    payload: OpsQuery, principal: CurrentPrincipal, service: Service
) -> dict[str, Any]:
    return service.query_operations(payload, principal)


@router.get("/tools")
def list_tools(principal: CurrentPrincipal, service: Service) -> list[dict[str, Any]]:
    require_scope(principal, "workorder:read")
    return service.gateway.list_tools()


@router.get("/tool-audit")
def tool_audit(principal: CurrentPrincipal, service: Service) -> list[dict[str, Any]]:
    require_scope(principal, "*")
    return service.gateway.audit_log()


@router.get("/traces")
def traces(
    principal: CurrentPrincipal,
    service: Service,
    service_request_id: str | None = None,
) -> list[dict[str, Any]]:
    require_scope(principal, "workorder:read")
    return service.traces.list(service_request_id)
