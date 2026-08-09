from __future__ import annotations

from typing import TYPE_CHECKING, Any

from roadmind.application.ports import (
    DiagnosisCapability,
    DispatchCapability,
    OperationsCapability,
    PartsCapability,
)
from roadmind.auth.users import UserStore
from roadmind.domain.auth import Principal, require_scope
from roadmind.domain.models import (
    Approval,
    ClosureApproval,
    ClosureRequest,
    DiagnosisMismatch,
    DispatchApproval,
    DispatchCandidate,
    ExpertDecision,
    OpsQuery,
    PartCandidate,
    PartsReservationRequest,
    Role,
    ServiceRequestCreate,
    TaskStatus,
    TimelineEvent,
    WorkOrder,
    WorkOrderStatus,
    utc_now,
)
from roadmind.domain.state_machine import transition
from roadmind.infra.observability import TraceRecorder
from roadmind.infra.outbox import OutboxStore
from roadmind.infra.pii_vault import PiiStore
from roadmind.infra.repository import WorkOrderRepository
from roadmind.mcp.gateway import ToolGateway
from roadmind.mcp.tools import RoadMindToolPort
from roadmind.workflows.langgraph_flows import (
    NativeApprovalWorkflow,
    build_mismatch_replan_graph,
    build_parallel_fulfillment_graph,
)
from roadmind.workflows.task_planner import WorkOrderPlanner

if TYPE_CHECKING:
    from roadmind.bootstrap import AppContainer


class RoadMindService:
    MAX_REPLANS = 3

    def __init__(self, container: AppContainer) -> None:
        self.repo: WorkOrderRepository = container.repo
        self.vault: PiiStore = container.vault
        self.traces: TraceRecorder = container.traces
        self.outbox: OutboxStore = container.outbox
        self.planner: WorkOrderPlanner = container.planner
        self.users: UserStore = container.users
        self.diagnosis: DiagnosisCapability = container.diagnosis_service
        self.dispatch: DispatchCapability = container.dispatch_service
        self.parts: PartsCapability = container.parts_service
        self.operations: OperationsCapability = container.operations_service
        self.settings = container.settings
        self.gateway: ToolGateway = container.gateway
        self.tools: RoadMindToolPort = container.tools
        self.native_approval = NativeApprovalWorkflow()

    def create_request(self, payload: ServiceRequestCreate, principal: Principal) -> WorkOrder:
        require_scope(principal, "workorder:create")
        decoded = self.tools.decode_vin(payload.vehicle.vin, principal)
        if not decoded["valid"]:
            raise ValueError("VIN failed DMS adapter validation")
        pii_ref = self.vault.put(
            {"reporter_name": payload.reporter_name, "reporter_phone": payload.reporter_phone}
        )
        order = WorkOrder(
            reporter_pii_ref=pii_ref,
            vehicle=payload.vehicle,
            symptom=payload.symptom,
            dtc_codes=[code.upper() for code in payload.dtc_codes],
            telemetry=payload.telemetry,
            service_mode=payload.service_mode,
            location=payload.location,
        )
        order.timeline.append(
            TimelineEvent(
                event_type="service_request.created",
                actor=principal.user_id,
                data={"thread_id": order.thread_id, "pii_ref": pii_ref},
            )
        )
        order.task_plan = self.planner.plan(order)
        transition(
            order,
            WorkOrderStatus.TRIAGED,
            actor="work_order_planner",
            reason="intent_and_route_ready",
        )
        self.repo.create(order)
        self.outbox.append(
            "service_request.created", {"service_request_id": order.service_request_id}
        )
        return order

    def list_orders(self, principal: Principal) -> list[WorkOrder]:
        require_scope(principal, "workorder:read")
        return self.repo.list()

    def get_order(self, order_id: str, principal: Principal) -> WorkOrder:
        require_scope(principal, "workorder:read")
        return self.repo.get(order_id)

    def run_diagnosis(self, order_id: str, principal: Principal) -> WorkOrder:
        require_scope(principal, "diagnosis:run")
        order = self.repo.get(order_id)
        expected = order.version
        if order.status == WorkOrderStatus.REDIAGNOSIS_REQUIRED:
            transition(
                order, WorkOrderStatus.DIAGNOSING, actor=principal.user_id, reason="replan_started"
            )
        elif order.status == WorkOrderStatus.TRIAGED:
            transition(
                order,
                WorkOrderStatus.DIAGNOSING,
                actor=principal.user_id,
                reason="diagnosis_started",
            )
        else:
            raise ValueError(f"cannot diagnose from {order.status}")
        with self.traces.span(
            "intelligent_maintenance_agent",
            "subagent",
            service_request_id=order_id,
            plan_version=order.task_plan.plan_version if order.task_plan else 1,
        ):
            system = Principal(user_id="maintenance_agent", role=Role.ADMIN)
            self.tools.get_live_signals(order_id, order.telemetry, system)
            order.diagnosis = self.diagnosis.diagnose(order)
        self._set_task(
            order, "diagnose", TaskStatus.SUCCEEDED, {"diagnosis_id": order.diagnosis.diagnosis_id}
        )
        approval = Approval(action="diagnosis.confirm", requested_role=Role.EXPERT)
        order.approvals.append(approval)
        transition(
            order,
            WorkOrderStatus.WAITING_EXPERT,
            actor="maintenance_agent",
            reason="preliminary_diagnosis_requires_human_confirmation",
        )
        order.timeline.append(
            TimelineEvent(
                event_type="diagnosis.preliminary_ready",
                actor="maintenance_agent",
                data={
                    "diagnosis_id": order.diagnosis.diagnosis_id,
                    "confidence": order.diagnosis.confidence,
                    "evidence_refs": [e.evidence_id for e in order.diagnosis.evidence],
                    "approval_id": approval.approval_id,
                },
            )
        )
        return self.repo.save(order, expected_version=expected)

    def confirm_diagnosis(
        self, order_id: str, decision: ExpertDecision, principal: Principal
    ) -> WorkOrder:
        require_scope(principal, "diagnosis:confirm")
        order = self.repo.get(order_id)
        expected = order.version
        if order.status != WorkOrderStatus.WAITING_EXPERT or not order.diagnosis:
            raise ValueError("no diagnosis is awaiting expert confirmation")
        if order.diagnosis.diagnosis_id != decision.diagnosis_id:
            raise ValueError("stale diagnosis decision")
        approval = self._pending_approval(order, "diagnosis.confirm")
        approval.status = "approved" if decision.approved else "rejected"
        approval.decided_by = principal.user_id
        approval.decided_at = utc_now()
        if not decision.approved:
            transition(
                order,
                WorkOrderStatus.REDIAGNOSIS_REQUIRED,
                actor=principal.user_id,
                reason=decision.comment or "expert_rejected_preliminary_diagnosis",
            )
            return self.repo.save(order, expected_version=expected)
        if not decision.confirmed_code:
            raise ValueError("approved diagnosis requires confirmed_code")
        order.diagnosis.confirmed_code = decision.confirmed_code.upper()
        order.diagnosis.confirmed_by = principal.user_id
        self._set_task(
            order, "expert_confirm", TaskStatus.SUCCEEDED, {"code": decision.confirmed_code}
        )
        transition(
            order,
            WorkOrderStatus.DIAGNOSIS_CONFIRMED,
            actor=principal.user_id,
            reason="expert_confirmed",
        )
        self._prepare_parallel_fulfillment(order)
        transition(
            order,
            WorkOrderStatus.FULFILLING,
            actor="orchestrator",
            reason="dispatch_and_parts_fanout_started",
        )
        return self.repo.save(order, expected_version=expected)

    def approve_dispatch(
        self, order_id: str, payload: DispatchApproval, principal: Principal
    ) -> WorkOrder:
        require_scope(principal, "dispatch:approve")
        order = self.repo.get(order_id)
        expected = order.version
        if order.status != WorkOrderStatus.FULFILLING:
            raise ValueError("work order is not in fulfillment")
        approval = self._pending_approval(order, "dispatch.assign")
        if approval.token != payload.approval_token:
            raise ValueError("invalid or stale approval token")
        self.dispatch.verify_assignment(order, payload.resource_id)
        self.tools.assign_resource(order_id, payload.resource_id, principal)
        order.selected_resource_id = payload.resource_id
        approval.status = "approved"
        approval.decided_by = principal.user_id
        approval.decided_at = utc_now()
        self._set_task(
            order, "dispatch", TaskStatus.SUCCEEDED, {"resource_id": payload.resource_id}
        )
        order.timeline.append(
            TimelineEvent(
                event_type="dispatch.assigned",
                actor=principal.user_id,
                data={"resource_id": payload.resource_id},
            )
        )
        self._advance_if_fulfillment_ready(order)
        return self.repo.save(order, expected_version=expected)

    def reserve_parts(
        self, order_id: str, payload: PartsReservationRequest, principal: Principal
    ) -> WorkOrder:
        require_scope(principal, "parts:reserve")
        order = self.repo.get(order_id)
        expected = order.version
        if order.status != WorkOrderStatus.FULFILLING:
            raise ValueError("work order is not in fulfillment")
        valid_codes = {part.part_code for part in order.parts_candidates}
        selected = list(payload.part_codes)
        if not set(selected).issubset(valid_codes):
            raise ValueError("requested part was not in the VIN-compatible candidate set")
        if payload.bring_both:
            oem = next((part.part_code for part in order.parts_candidates if part.is_oem), None)
            aftermarket = next(
                (part.part_code for part in order.parts_candidates if not part.is_oem), None
            )
            selected = list(
                dict.fromkeys([*selected, *[code for code in [oem, aftermarket] if code]])
            )
        if order.reserved_part_codes:
            if order.reserved_part_codes == selected:
                return order
            raise ValueError("work order already has a different active parts reservation")
        self.tools.reserve_inventory(order_id, selected, principal)
        order.reserved_part_codes = selected
        self._set_task(order, "parts", TaskStatus.SUCCEEDED, {"part_codes": selected})
        order.timeline.append(
            TimelineEvent(
                event_type="parts.reserved",
                actor=principal.user_id,
                data={"part_codes": selected, "bring_both": payload.bring_both},
            )
        )
        self._advance_if_fulfillment_ready(order)
        return self.repo.save(order, expected_version=expected)

    def start_service(self, order_id: str, principal: Principal) -> WorkOrder:
        require_scope(principal, "service:execute")
        order = self.repo.get(order_id)
        expected = order.version
        transition(
            order,
            WorkOrderStatus.IN_SERVICE,
            actor=principal.user_id,
            reason="onsite_service_started",
        )
        return self.repo.save(order, expected_version=expected)

    def resume_manual_takeover(self, order_id: str, principal: Principal) -> WorkOrder:
        require_scope(principal, "diagnosis:run")
        order = self.repo.get(order_id)
        expected = order.version
        if order.status != WorkOrderStatus.MANUAL_TAKEOVER:
            raise ValueError("work order is not in manual takeover")
        order.degraded_mode = True
        transition(
            order,
            WorkOrderStatus.REDIAGNOSIS_REQUIRED,
            actor=principal.user_id,
            reason="manual_takeover_resume_degraded",
        )
        order.timeline.append(
            TimelineEvent(
                event_type="manual_takeover.resumed",
                actor=principal.user_id,
                data={"degraded_mode": True},
            )
        )
        return self.repo.save(order, expected_version=expected)

    def report_mismatch(
        self, order_id: str, payload: DiagnosisMismatch, principal: Principal
    ) -> WorkOrder:
        require_scope(principal, "diagnosis:run")
        order = self.repo.get(order_id)
        expected = order.version
        if order.status not in {
            WorkOrderStatus.FULFILLING,
            WorkOrderStatus.READY_FOR_SERVICE,
            WorkOrderStatus.IN_SERVICE,
        }:
            raise ValueError("mismatch can only be raised during fulfillment or service")
        old_version = order.task_plan.plan_version if order.task_plan else 1

        def freeze(state: dict[str, Any]) -> dict[str, Any]:
            return {"frozen": True}

        def compensate(state: dict[str, Any]) -> dict[str, Any]:
            system = Principal(user_id="orchestrator", role=Role.ADMIN)
            released = self.tools.release_fulfillment(order_id, order.selected_resource_id, system)
            return {
                "compensated": True,
                **released,
            }

        graph = build_mismatch_replan_graph(freeze, compensate)
        result = graph.invoke({"old_plan_version": old_version, "reason": payload.evidence})
        order.replan_count += 1
        frozen_versions = [
            *(order.task_plan.frozen_versions if order.task_plan else []),
            old_version,
        ]
        order.task_plan = self.planner.plan(
            order,
            version=result["new_plan_version"],
            reason="diagnosis_mismatch_replan",
        )
        order.task_plan.frozen_versions = frozen_versions
        order.selected_resource_id = None
        order.reserved_part_codes = []
        order.dispatch_candidates = []
        order.parts_candidates = []
        if order.diagnosis:
            order.diagnosis.confirmed_code = None
            order.diagnosis.confirmed_by = None
        transition(
            order,
            WorkOrderStatus.REDIAGNOSIS_REQUIRED,
            actor=principal.user_id,
            reason=f"actual={payload.actual_code}; {payload.evidence}",
        )
        order.timeline.append(
            TimelineEvent(
                event_type="saga.compensated",
                actor="orchestrator",
                data=result,
            )
        )
        if order.replan_count > self.MAX_REPLANS:
            transition(
                order,
                WorkOrderStatus.MANUAL_TAKEOVER,
                actor="orchestrator",
                reason="maximum_replan_count_exceeded",
            )
        return self.repo.save(order, expected_version=expected)

    def close_order(
        self, order_id: str, payload: ClosureRequest, principal: Principal
    ) -> WorkOrder:
        require_scope(principal, "service:execute")
        order = self.repo.get(order_id)
        expected = order.version
        if order.status != WorkOrderStatus.IN_SERVICE:
            raise ValueError("only an in-service work order can be closed")
        transition(
            order,
            WorkOrderStatus.WAITING_CLOSE_APPROVAL,
            actor=principal.user_id,
            reason="service_result_submitted",
        )
        closure_result = {
            "resolution": payload.resolution,
            "actual_part_codes": payload.actual_part_codes,
            "customer_rating": payload.customer_rating,
        }
        self._set_task(order, "service", TaskStatus.WAITING_APPROVAL, closure_result)
        approval = Approval(action="service.close", requested_role=Role.EXPERT)
        order.approvals.append(approval)
        order.timeline.append(
            TimelineEvent(
                event_type="service.close_requested",
                actor=principal.user_id,
                data={"approval_id": approval.approval_id, **closure_result},
            )
        )
        return self.repo.save(order, expected_version=expected)

    def approve_closure(
        self, order_id: str, payload: ClosureApproval, principal: Principal
    ) -> WorkOrder:
        require_scope(principal, "service:close_approve")
        order = self.repo.get(order_id)
        expected = order.version
        if order.status != WorkOrderStatus.WAITING_CLOSE_APPROVAL:
            raise ValueError("no closure is awaiting approval")
        approval = self._pending_approval(order, "service.close")
        if approval.token != payload.approval_token:
            raise ValueError("invalid or stale approval token")
        approval.status = "approved" if payload.approved else "rejected"
        approval.decided_by = principal.user_id
        approval.decided_at = utc_now()
        service_task = self._task(order, "service")
        if not payload.approved:
            service_task.status = TaskStatus.RUNNING
            transition(
                order,
                WorkOrderStatus.IN_SERVICE,
                actor=principal.user_id,
                reason=payload.comment or "closure_rejected",
            )
            return self.repo.save(order, expected_version=expected)
        transition(
            order,
            WorkOrderStatus.CLOSED,
            actor=principal.user_id,
            reason=payload.comment or "closure_invariants_approved",
        )
        service_task.status = TaskStatus.SUCCEEDED
        closure_result = service_task.result
        self._set_task(
            order,
            "archive",
            TaskStatus.SUCCEEDED,
            {
                "quality_gate": "pending_offline_review",
                "customer_rating": closure_result["customer_rating"],
            },
        )
        order.timeline.append(
            TimelineEvent(
                event_type="knowledge.case_candidate_created",
                actor="closure_workflow",
                data={
                    "resolution": closure_result["resolution"],
                    "actual_part_codes": closure_result["actual_part_codes"],
                    "publication_status": "quarantine_pending_quality_review",
                },
            )
        )
        saved = self.repo.save(order, expected_version=expected)
        self.outbox.append(
            "workorder.closed",
            {
                "service_request_id": order_id,
                "plan_version": order.task_plan.plan_version if order.task_plan else 1,
            },
        )
        return saved

    def query_operations(self, query: OpsQuery, principal: Principal) -> dict[str, Any]:
        require_scope(principal, "metrics:query")
        if query.scenario_delta is not None:
            require_scope(principal, "metrics:simulate")
        with self.traces.span("operations_agent", "subagent", actor=principal.user_id):
            return self.operations.answer(
                query.question,
                self.repo.list(),
                principal=principal,
                scenario_delta=query.scenario_delta,
            )

    def _prepare_parallel_fulfillment(self, order: WorkOrder) -> None:
        def dispatch_node(state: dict[str, Any]) -> dict[str, Any]:
            return {
                "dispatch_candidates": [
                    item.model_dump() for item in self.dispatch.candidates(order)
                ]
            }

        def parts_node(state: dict[str, Any]) -> dict[str, Any]:
            system = Principal(user_id="orchestrator", role=Role.ADMIN)
            stock = self.tools.inventory_snapshot(order.service_request_id, system)
            return {
                "parts_candidates": [
                    item.model_dump() for item in self.parts.candidates(order, stock=stock)
                ]
            }

        graph = build_parallel_fulfillment_graph(dispatch_node, parts_node)
        with self.traces.span(
            "parallel_fulfillment",
            "workflow",
            service_request_id=order.service_request_id,
            plan_version=order.task_plan.plan_version if order.task_plan else 1,
        ):
            result = graph.invoke({"service_request_id": order.service_request_id})
        order.dispatch_candidates = [
            DispatchCandidate.model_validate(item) for item in result["dispatch_candidates"]
        ]
        order.parts_candidates = [
            PartCandidate.model_validate(item) for item in result["parts_candidates"]
        ]
        order.approvals.append(Approval(action="dispatch.assign", requested_role=Role.DISPATCHER))
        self._set_task(order, "dispatch", TaskStatus.WAITING_APPROVAL, {})
        self._set_task(order, "parts", TaskStatus.RUNNING, {})
        order.timeline.append(
            TimelineEvent(
                event_type="fulfillment.candidates_ready",
                actor="parallel_fulfillment",
                data={
                    "dispatch_candidates": len(order.dispatch_candidates),
                    "parts_candidates": len(order.parts_candidates),
                    "joined": result["joined"],
                },
            )
        )

    @staticmethod
    def _pending_approval(order: WorkOrder, action: str) -> Approval:
        approval = next(
            (
                item
                for item in reversed(order.approvals)
                if item.action == action and item.status == "pending"
            ),
            None,
        )
        if approval is None:
            raise ValueError(f"no pending approval for {action}")
        return approval

    @staticmethod
    def _set_task(
        order: WorkOrder, task_id: str, status: TaskStatus, result: dict[str, Any]
    ) -> None:
        if not order.task_plan:
            return
        task = next(item for item in order.task_plan.tasks if item.task_id == task_id)
        task.status = status
        task.result = result

    @staticmethod
    def _task(order: WorkOrder, task_id: str):
        if not order.task_plan:
            raise ValueError("work order has no task plan")
        return next(item for item in order.task_plan.tasks if item.task_id == task_id)

    @staticmethod
    def _advance_if_fulfillment_ready(order: WorkOrder) -> None:
        if order.selected_resource_id and order.reserved_part_codes:
            transition(
                order,
                WorkOrderStatus.READY_FOR_SERVICE,
                actor="parallel_fulfillment",
                reason="dispatch_approved AND parts_ready",
            )
