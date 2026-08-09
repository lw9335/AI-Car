from __future__ import annotations

from collections.abc import Callable
from typing import Any

from roadmind.application.presentation import present_work_order
from roadmind.application.service import RoadMindService
from roadmind.assistant.models import AssistantExecution
from roadmind.domain.auth import Principal
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


class BusinessAgentSupervisor:
    """Creates a request-scoped control surface over the four business agents."""

    def __init__(self, service: RoadMindService) -> None:
        self._service = service

    def bind(
        self,
        principal: Principal,
        *,
        confirmed_actions: set[str] | None = None,
    ) -> BoundBusinessAgentTools:
        return BoundBusinessAgentTools(
            self._service,
            principal,
            confirmed_actions=confirmed_actions or set(),
        )


class BoundBusinessAgentTools:
    """Strongly typed tools bound to one authenticated user and one chat turn."""

    TOOL_METHODS = (
        "list_work_orders",
        "get_work_order",
        "create_work_order",
        "diagnosis_agent_run",
        "diagnosis_agent_confirm",
        "dispatch_agent_approve",
        "parts_agent_reserve",
        "operations_agent_query",
        "start_field_service",
        "diagnosis_agent_report_mismatch",
        "resume_manual_takeover",
        "request_service_closure",
        "approve_service_closure",
    )
    COMMANDS = (
        "workorder.list",
        "workorder.get",
        "workorder.create",
        "diagnosis.run",
        "diagnosis.confirm",
        "dispatch.approve",
        "parts.reserve",
        "operations.query",
        "service.start",
        "diagnosis.mismatch",
        "diagnosis.resume",
        "service.close",
        "service.close_approve",
    )

    def __init__(
        self,
        service: RoadMindService,
        principal: Principal,
        *,
        confirmed_actions: set[str],
    ) -> None:
        self._service = service
        self._principal = principal
        self._confirmed_actions = confirmed_actions
        self.executions: list[AssistantExecution] = []

    def tool_functions(self) -> list[Callable[..., Any]]:
        return [getattr(self, name) for name in self.TOOL_METHODS]

    def list_work_orders(self) -> dict[str, Any]:
        """List work orders visible to the current user."""

        orders = [
            present_work_order(order, self._principal)
            for order in self._service.list_orders(self._principal)
        ]
        return self._record("work_order", "workorder.list", {"orders": orders})

    def get_work_order(self, order_id: str) -> dict[str, Any]:
        """Get one work order, including current state, candidates and pending approvals."""

        order = self._service.get_order(order_id, self._principal)
        return self._record(
            "work_order",
            "workorder.get",
            present_work_order(order, self._principal),
        )

    def create_work_order(self, request: dict[str, Any]) -> dict[str, Any]:
        """Create a work order from a complete ServiceRequestCreate object."""

        payload = ServiceRequestCreate.model_validate(request)
        order = self._service.create_request(payload, self._principal)
        return self._record(
            "work_order",
            "workorder.create",
            present_work_order(order, self._principal),
        )

    def diagnosis_agent_run(self, order_id: str) -> dict[str, Any]:
        """Run the diagnosis agent for a triaged or rediagnosis-required work order."""

        order = self._service.run_diagnosis(order_id, self._principal)
        return self._record(
            "diagnosis_agent",
            "diagnosis.run",
            present_work_order(order, self._principal),
        )

    def diagnosis_agent_confirm(
        self,
        order_id: str,
        diagnosis_id: str,
        approved: bool,
        confirmed_code: str = "",
        comment: str = "",
    ) -> dict[str, Any]:
        """Record an expert's explicit diagnosis decision and start fulfillment when approved."""

        self._require_confirmation("diagnosis.confirm")
        decision = ExpertDecision(
            diagnosis_id=diagnosis_id,
            approved=approved,
            confirmed_code=confirmed_code or None,
            comment=comment,
        )
        order = self._service.confirm_diagnosis(order_id, decision, self._principal)
        return self._record(
            "diagnosis_agent",
            "diagnosis.confirm",
            present_work_order(order, self._principal),
        )

    def dispatch_agent_approve(
        self,
        order_id: str,
        resource_id: str,
        approval_token: str,
    ) -> dict[str, Any]:
        """Approve the dispatch agent candidate selected by a human dispatcher."""

        self._require_confirmation("dispatch.approve")
        order = self._service.approve_dispatch(
            order_id,
            DispatchApproval(resource_id=resource_id, approval_token=approval_token),
            self._principal,
        )
        return self._record(
            "dispatch_agent",
            "dispatch.approve",
            present_work_order(order, self._principal),
        )

    def parts_agent_reserve(
        self,
        order_id: str,
        part_codes: list[str],
        bring_both: bool = False,
    ) -> dict[str, Any]:
        """Reserve VIN-compatible parts after an explicit human confirmation."""

        self._require_confirmation("parts.reserve")
        order = self._service.reserve_parts(
            order_id,
            PartsReservationRequest(part_codes=part_codes, bring_both=bring_both),
            self._principal,
        )
        return self._record(
            "parts_agent",
            "parts.reserve",
            present_work_order(order, self._principal),
        )

    def operations_agent_query(
        self,
        question: str,
        scope: str = "all",
        scenario_delta: float | None = None,
    ) -> dict[str, Any]:
        """Ask the operations agent for metrics, analysis or a scenario simulation."""

        result = self._service.query_operations(
            OpsQuery(question=question, scope=scope, scenario_delta=scenario_delta),
            self._principal,
        )
        return self._record("operations_agent", "operations.query", result)

    def start_field_service(self, order_id: str) -> dict[str, Any]:
        """Start on-site service after dispatch and parts fulfillment are ready."""

        self._require_confirmation("service.start")
        order = self._service.start_service(order_id, self._principal)
        return self._record(
            "service_workflow",
            "service.start",
            present_work_order(order, self._principal),
        )

    def diagnosis_agent_report_mismatch(
        self,
        order_id: str,
        actual_code: str,
        evidence: str,
    ) -> dict[str, Any]:
        """Report field evidence that conflicts with the diagnosis and trigger compensation."""

        self._require_confirmation("diagnosis.mismatch")
        order = self._service.report_mismatch(
            order_id,
            DiagnosisMismatch(actual_code=actual_code, evidence=evidence),
            self._principal,
        )
        return self._record(
            "diagnosis_agent",
            "diagnosis.mismatch",
            present_work_order(order, self._principal),
        )

    def resume_manual_takeover(self, order_id: str) -> dict[str, Any]:
        """Resume a manually reviewed work order in degraded rediagnosis mode."""

        self._require_confirmation("diagnosis.resume")
        order = self._service.resume_manual_takeover(order_id, self._principal)
        return self._record(
            "diagnosis_agent",
            "diagnosis.resume",
            present_work_order(order, self._principal),
        )

    def request_service_closure(
        self,
        order_id: str,
        resolution: str,
        actual_part_codes: list[str],
        customer_rating: int,
    ) -> dict[str, Any]:
        """Submit the field-service result for expert closure approval."""

        self._require_confirmation("service.close")
        order = self._service.close_order(
            order_id,
            ClosureRequest(
                resolution=resolution,
                actual_part_codes=actual_part_codes,
                customer_rating=customer_rating,
            ),
            self._principal,
        )
        return self._record(
            "service_workflow",
            "service.close",
            present_work_order(order, self._principal),
        )

    def approve_service_closure(
        self,
        order_id: str,
        approval_token: str,
        approved: bool,
        comment: str = "",
    ) -> dict[str, Any]:
        """Record an expert's explicit closure decision using the pending approval token."""

        self._require_confirmation("service.close_approve")
        order = self._service.approve_closure(
            order_id,
            ClosureApproval(
                approval_token=approval_token,
                approved=approved,
                comment=comment,
            ),
            self._principal,
        )
        return self._record(
            "service_workflow",
            "service.close_approve",
            present_work_order(order, self._principal),
        )

    def execute_command(self, command: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a structured command in deterministic/offline supervisor mode."""

        command_methods = {
            "workorder.list": self.list_work_orders,
            "workorder.get": self.get_work_order,
            "workorder.create": self.create_work_order,
            "diagnosis.run": self.diagnosis_agent_run,
            "diagnosis.confirm": self.diagnosis_agent_confirm,
            "dispatch.approve": self.dispatch_agent_approve,
            "parts.reserve": self.parts_agent_reserve,
            "operations.query": self.operations_agent_query,
            "service.start": self.start_field_service,
            "diagnosis.mismatch": self.diagnosis_agent_report_mismatch,
            "diagnosis.resume": self.resume_manual_takeover,
            "service.close": self.request_service_closure,
            "service.close_approve": self.approve_service_closure,
        }
        method = command_methods.get(command)
        if method is None:
            raise ValueError(f"unsupported supervisor command: {command}")
        return method(**arguments)

    def _require_confirmation(self, action: str) -> None:
        if action not in self._confirmed_actions:
            raise ValueError(
                f"assistant action {action} requires explicit confirmation in confirmed_actions"
            )

    def _record(
        self,
        capability: str,
        operation: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        self.executions.append(
            AssistantExecution(
                capability=capability,
                operation=operation,
                result=result,
            )
        )
        return result
