from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from roadmind.api.dependencies import (
    assistant_from_request,
    gateway_from_request,
    get_principal,
    service_from_request,
)
from roadmind.application.presentation import present_work_order
from roadmind.application.service import RoadMindService
from roadmind.assistant.models import (
    AssistantChatRequest,
    AssistantChatResponse,
    ConversationView,
)
from roadmind.assistant.service import EnterpriseAssistantService
from roadmind.auth.users import create_access_token, verify_password
from roadmind.domain.auth import Principal, require_scope
from roadmind.domain.models import (
    ClosureApproval,
    ClosureRequest,
    DiagnosisMismatch,
    DispatchApproval,
    ExpertDecision,
    OpsQuery,
    PartsReservationRequest,
    ServiceRequestCreate,
)
from roadmind.mcp.gateway import ToolGateway
from roadmind.settings import get_settings

router = APIRouter(prefix="/api/v1")
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
Service = Annotated[RoadMindService, Depends(service_from_request)]
Gateway = Annotated[ToolGateway, Depends(gateway_from_request)]
Assistant = Annotated[EnterpriseAssistantService, Depends(assistant_from_request)]


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, str]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "roadmind", "version": "0.1.0"}


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, service: Service) -> LoginResponse:
    user = service.users.get_by_username(payload.username)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    settings = get_settings()
    token = create_access_token(
        user=user, secret=settings.jwt_secret, ttl_minutes=settings.jwt_ttl_minutes
    )
    return LoginResponse(access_token=token, user=user.public_dict())


@router.get("/auth/me")
def me(principal: CurrentPrincipal, service: Service) -> dict[str, str]:
    user = service.users.get_by_id(principal.user_id)
    if user is None:
        return {
            "user_id": principal.user_id,
            "username": principal.user_id,
            "role": principal.role.value,
            "region": principal.region,
        }
    return user.public_dict()


@router.post("/assistant/chat", response_model=AssistantChatResponse)
def assistant_chat(
    payload: AssistantChatRequest,
    principal: CurrentPrincipal,
    assistant: Assistant,
) -> AssistantChatResponse:
    return assistant.chat(payload, principal)


@router.get(
    "/assistant/conversations/{conversation_id}",
    response_model=ConversationView,
)
def assistant_conversation(
    conversation_id: str,
    principal: CurrentPrincipal,
    assistant: Assistant,
) -> ConversationView:
    return assistant.conversation(conversation_id, principal)


@router.post("/work-orders", status_code=201)
def create_work_order(
    payload: ServiceRequestCreate, principal: CurrentPrincipal, service: Service
) -> dict[str, Any]:
    return present_work_order(service.create_request(payload, principal), principal)


@router.get("/work-orders")
def list_work_orders(principal: CurrentPrincipal, service: Service) -> list[dict[str, Any]]:
    return [present_work_order(order, principal) for order in service.list_orders(principal)]


@router.get("/work-orders/{order_id}")
def get_work_order(order_id: str, principal: CurrentPrincipal, service: Service) -> dict[str, Any]:
    return present_work_order(service.get_order(order_id, principal), principal)


@router.post("/work-orders/{order_id}/diagnose")
def diagnose(order_id: str, principal: CurrentPrincipal, service: Service) -> dict[str, Any]:
    return present_work_order(service.run_diagnosis(order_id, principal), principal)


@router.post("/work-orders/{order_id}/expert-confirm")
def confirm_diagnosis(
    order_id: str,
    payload: ExpertDecision,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_work_order(service.confirm_diagnosis(order_id, payload, principal), principal)


@router.post("/work-orders/{order_id}/dispatch/approve")
def approve_dispatch(
    order_id: str,
    payload: DispatchApproval,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_work_order(service.approve_dispatch(order_id, payload, principal), principal)


@router.post("/work-orders/{order_id}/parts/reserve")
def reserve_parts(
    order_id: str,
    payload: PartsReservationRequest,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_work_order(service.reserve_parts(order_id, payload, principal), principal)


@router.post("/work-orders/{order_id}/service/start")
def start_service(order_id: str, principal: CurrentPrincipal, service: Service) -> dict[str, Any]:
    return present_work_order(service.start_service(order_id, principal), principal)


@router.post("/work-orders/{order_id}/mismatch")
def report_mismatch(
    order_id: str,
    payload: DiagnosisMismatch,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_work_order(service.report_mismatch(order_id, payload, principal), principal)


@router.post("/work-orders/{order_id}/manual-takeover/resume")
def resume_manual_takeover(
    order_id: str, principal: CurrentPrincipal, service: Service
) -> dict[str, Any]:
    return present_work_order(service.resume_manual_takeover(order_id, principal), principal)


@router.post("/work-orders/{order_id}/close")
def close_work_order(
    order_id: str,
    payload: ClosureRequest,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_work_order(service.close_order(order_id, payload, principal), principal)


@router.post("/work-orders/{order_id}/close/approve")
def approve_closure(
    order_id: str,
    payload: ClosureApproval,
    principal: CurrentPrincipal,
    service: Service,
) -> dict[str, Any]:
    return present_work_order(service.approve_closure(order_id, payload, principal), principal)


@router.post("/operations/query")
def query_operations(
    payload: OpsQuery, principal: CurrentPrincipal, service: Service
) -> dict[str, Any]:
    return service.query_operations(payload, principal)


@router.get("/tools")
def list_tools(principal: CurrentPrincipal, gateway: Gateway) -> list[dict[str, Any]]:
    require_scope(principal, "workorder:read")
    return gateway.list_tools(principal)


@router.get("/tool-audit")
def tool_audit(principal: CurrentPrincipal, gateway: Gateway) -> list[dict[str, Any]]:
    require_scope(principal, "*")
    return gateway.audit_log(principal)


@router.get("/traces")
def traces(
    principal: CurrentPrincipal,
    service: Service,
    service_request_id: str | None = None,
) -> list[dict[str, Any]]:
    require_scope(principal, "workorder:read")
    return service.traces.list(service_request_id)
