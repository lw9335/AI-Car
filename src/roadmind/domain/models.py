from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class Brand(StrEnum):
    FOTON_AUMAN = "foton_auman"
    BAIC_TRUCK = "baic_truck"
    DEEPWAY = "deepway"


class PowerType(StrEnum):
    DIESEL = "diesel"
    ELECTRIC = "electric"


class Role(StrEnum):
    INFORMATION_OFFICER = "information_officer"
    TECHNICIAN = "technician"
    EXPERT = "expert"
    DISPATCHER = "dispatcher"
    PARTS_MANAGER = "parts_manager"
    OPERATIONS = "operations"
    ADMIN = "admin"


class Domain(StrEnum):
    MAINTENANCE = "maintenance"
    DISPATCH = "dispatch"
    PARTS = "parts"
    OPERATIONS = "operations"


class WorkOrderStatus(StrEnum):
    REPORTED = "reported"
    TRIAGED = "triaged"
    DIAGNOSING = "diagnosing"
    WAITING_EXPERT = "waiting_expert"
    DIAGNOSIS_CONFIRMED = "diagnosis_confirmed"
    FULFILLING = "fulfilling"
    READY_FOR_SERVICE = "ready_for_service"
    IN_SERVICE = "in_service"
    REDIAGNOSIS_REQUIRED = "rediagnosis_required"
    WAITING_CLOSE_APPROVAL = "waiting_close_approval"
    CLOSED = "closed"
    MANUAL_TAKEOVER = "manual_takeover"


class ServiceMode(StrEnum):
    OEM_AUTHORIZED = "oem_authorized"
    RETAIL_RETURNING = "retail_returning"
    PARTNER_REPAIR = "partner_repair"
    FLEET_SERVICE = "fleet_service"


class DiagnosisMode(StrEnum):
    OEM_SPECIAL_TOOL = "mode_a_oem_special_tool"
    EV_MANUAL_RAG = "mode_b_ev_manual_rag"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    FROZEN = "frozen"
    COMPENSATED = "compensated"


class VehicleProfile(BaseModel):
    vin: str = Field(min_length=8, max_length=32)
    brand: Brand
    model: str
    power_type: PowerType
    model_year: int = Field(ge=2015, le=2035)
    configuration_code: str


class ServiceRequestCreate(BaseModel):
    reporter_name: str = Field(min_length=2, max_length=64)
    reporter_phone: str = Field(min_length=6, max_length=32)
    vehicle: VehicleProfile
    symptom: str = Field(min_length=4, max_length=2000)
    dtc_codes: list[str] = Field(default_factory=list)
    telemetry: dict[str, float] = Field(default_factory=dict)
    service_mode: ServiceMode = ServiceMode.OEM_AUTHORIZED
    location: str = Field(default="佛山顺德", max_length=120)


class EvidenceRef(BaseModel):
    evidence_id: str
    source_type: str
    title: str
    section: str
    brand: Brand
    model: str | None = None
    version: str
    score: float = Field(ge=0, le=1)
    excerpt: str


class DiagnosisHypothesis(BaseModel):
    code: str
    title: str
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    safety_level: str
    evidence_refs: list[str]


class DiagnosisPackage(BaseModel):
    diagnosis_id: str = Field(default_factory=lambda: f"diag_{uuid4().hex[:12]}")
    mode: DiagnosisMode
    hypotheses: list[DiagnosisHypothesis]
    sop_steps: list[str]
    required_tools: list[str]
    candidate_part_codes: list[str]
    evidence: list[EvidenceRef]
    confidence: float = Field(ge=0, le=1)
    conflicts: list[str] = Field(default_factory=list)
    requires_expert: bool = True
    confirmed_code: str | None = None
    confirmed_by: str | None = None


class DispatchCandidate(BaseModel):
    resource_id: str
    display_name: str
    resource_type: str
    skills: list[str]
    distance_km: float
    eta_minutes: int
    workload: int
    score: float
    constraint_reasons: list[str]


class PartCandidate(BaseModel):
    part_code: str
    name: str
    compatibility: str
    source: str
    stock: int
    eta_hours: int
    unit_price: float
    is_oem: bool
    evidence_refs: list[str]


class TaskItem(BaseModel):
    task_id: str
    domain: Domain
    action: str
    depends_on: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: dict[str, Any] = Field(default_factory=dict)


class TaskPlan(BaseModel):
    plan_version: int = 1
    tasks: list[TaskItem]
    frozen_versions: list[int] = Field(default_factory=list)
    reason: str = "initial_plan"


class TimelineEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:12]}")
    event_type: str
    actor: str
    at: datetime = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)


class Approval(BaseModel):
    approval_id: str = Field(default_factory=lambda: f"apr_{uuid4().hex[:12]}")
    action: str
    requested_role: Role
    status: str = "pending"
    token: str = Field(default_factory=lambda: uuid4().hex)
    decided_by: str | None = None
    decided_at: datetime | None = None


class WorkOrder(BaseModel):
    service_request_id: str = Field(default_factory=lambda: f"sr_{uuid4().hex[:12]}")
    thread_id: str | None = None
    version: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    status: WorkOrderStatus = WorkOrderStatus.REPORTED
    reporter_pii_ref: str
    vehicle: VehicleProfile
    symptom: str
    dtc_codes: list[str]
    telemetry: dict[str, float]
    service_mode: ServiceMode
    location: str
    diagnosis: DiagnosisPackage | None = None
    dispatch_candidates: list[DispatchCandidate] = Field(default_factory=list)
    selected_resource_id: str | None = None
    parts_candidates: list[PartCandidate] = Field(default_factory=list)
    reserved_part_codes: list[str] = Field(default_factory=list)
    task_plan: TaskPlan | None = None
    approvals: list[Approval] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    degraded_mode: bool = False
    replan_count: int = 0

    @model_validator(mode="after")
    def set_thread_id(self) -> WorkOrder:
        if self.thread_id is None:
            self.thread_id = self.service_request_id
        return self


class ExpertDecision(BaseModel):
    diagnosis_id: str
    approved: bool
    confirmed_code: str | None = None
    comment: str = ""


class DispatchApproval(BaseModel):
    resource_id: str
    approval_token: str


class PartsReservationRequest(BaseModel):
    part_codes: list[str]
    bring_both: bool = False


class DiagnosisMismatch(BaseModel):
    actual_code: str
    evidence: str


class ClosureRequest(BaseModel):
    resolution: str = Field(min_length=4, max_length=1000)
    actual_part_codes: list[str] = Field(default_factory=list)
    customer_rating: int = Field(ge=1, le=5)


class ClosureApproval(BaseModel):
    approval_token: str
    approved: bool
    comment: str = ""


class OpsQuery(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    scope: str = "all"
    scenario_delta: float | None = None
