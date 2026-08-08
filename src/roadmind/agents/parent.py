from __future__ import annotations

from dataclasses import dataclass

from roadmind.domain.models import Domain, TaskItem, TaskPlan, WorkOrder


@dataclass
class ParentDecision:
    intent: str
    missing_fields: list[str]
    routed_domains: list[Domain]
    rationale: str


class DeterministicParentAgent:
    """Offline-safe parent with the same structured contract as the LLM parent."""

    def understand(self, order: WorkOrder) -> ParentDecision:
        missing = []
        if not order.dtc_codes:
            missing.append("dtc_codes")
        if not order.telemetry:
            missing.append("telemetry")
        return ParentDecision(
            intent="commercial_vehicle_after_sales_service",
            missing_fields=missing,
            routed_domains=[Domain.MAINTENANCE, Domain.DISPATCH, Domain.PARTS],
            rationale="先诊断，专家确认后并行准备人员/工具与配件，结案后沉淀运营数据。",
        )

    def plan(self, order: WorkOrder, *, version: int = 1, reason: str = "initial_plan") -> TaskPlan:
        return TaskPlan(
            plan_version=version,
            reason=reason,
            tasks=[
                TaskItem(task_id="diagnose", domain=Domain.MAINTENANCE, action="run_diagnosis"),
                TaskItem(
                    task_id="expert_confirm",
                    domain=Domain.MAINTENANCE,
                    action="human_confirm",
                    depends_on=["diagnose"],
                ),
                TaskItem(
                    task_id="dispatch",
                    domain=Domain.DISPATCH,
                    action="candidate_reserve_assign",
                    depends_on=["expert_confirm"],
                ),
                TaskItem(
                    task_id="parts",
                    domain=Domain.PARTS,
                    action="recommend_reserve",
                    depends_on=["expert_confirm"],
                ),
                TaskItem(
                    task_id="service",
                    domain=Domain.MAINTENANCE,
                    action="execute_and_close",
                    depends_on=["dispatch", "parts"],
                ),
                TaskItem(
                    task_id="archive",
                    domain=Domain.OPERATIONS,
                    action="quality_gate_and_archive",
                    depends_on=["service"],
                ),
            ],
        )


class DeepAgentsParentFactory:
    """Paid-model adapter; imported lazily so the verified demo needs no API key."""

    @staticmethod
    def create(*, model: object, tools: list[object], system_prompt: str):
        try:
            from deepagents import create_deep_agent
        except ImportError as exc:
            raise RuntimeError("install the 'agent' extra to enable Deep Agents") from exc
        return create_deep_agent(model=model, tools=tools, system_prompt=system_prompt)
