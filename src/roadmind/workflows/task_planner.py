from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

from roadmind.domain.models import Domain, TaskItem, TaskPlan, WorkOrder
from roadmind.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class PlanningDecision:
    intent: str
    missing_fields: list[str]
    routed_domains: list[Domain]
    rationale: str


class WorkOrderPlanner(Protocol):
    """Produces an auditable task DAG; it is not the interactive supervisor."""

    def understand(self, order: WorkOrder) -> PlanningDecision: ...

    def plan(
        self,
        order: WorkOrder,
        *,
        version: int = 1,
        reason: str = "initial_plan",
    ) -> TaskPlan: ...


class DeterministicWorkOrderPlanner:
    """Offline-safe planner with the same structured contract as the LLM planner."""

    def understand(self, order: WorkOrder) -> PlanningDecision:
        missing = []
        if not order.dtc_codes:
            missing.append("dtc_codes")
        if not order.telemetry:
            missing.append("telemetry")
        return PlanningDecision(
            intent="commercial_vehicle_after_sales_service",
            missing_fields=missing,
            routed_domains=[Domain.MAINTENANCE, Domain.DISPATCH, Domain.PARTS],
            rationale=("先诊断，专家确认后并行准备人员、工具与配件，结案后沉淀运营数据。"),
        )

    def plan(
        self,
        order: WorkOrder,
        *,
        version: int = 1,
        reason: str = "initial_plan",
    ) -> TaskPlan:
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


class OpenRouterWorkOrderPlanner:
    """OpenAI-compatible planner via OpenRouter; falls back to deterministic rules."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fallback = DeterministicWorkOrderPlanner()

    def understand(self, order: WorkOrder) -> PlanningDecision:
        try:
            raw = self._invoke(
                system=(
                    "You are the RoadMind work-order planner. Return ONLY JSON with keys "
                    "intent, missing_fields, routed_domains, rationale."
                ),
                user=(
                    f"VIN={order.vehicle.vin}; brand={order.vehicle.brand}; "
                    f"power={order.vehicle.power_type}; symptom={order.symptom}; "
                    f"dtc={order.dtc_codes}; telemetry={order.telemetry}"
                ),
            )
            domains = [Domain(item) for item in raw.get("routed_domains", [])]
            if not domains:
                return self._fallback.understand(order)
            return PlanningDecision(
                intent=str(raw.get("intent") or "commercial_vehicle_after_sales_service"),
                missing_fields=[str(item) for item in raw.get("missing_fields", [])],
                routed_domains=domains,
                rationale=str(raw.get("rationale") or "llm_planner"),
            )
        except Exception:
            logger.exception("OpenRouter planner understand failed; using deterministic fallback")
            return self._fallback.understand(order)

    def plan(
        self,
        order: WorkOrder,
        *,
        version: int = 1,
        reason: str = "initial_plan",
    ) -> TaskPlan:
        plan = self._fallback.plan(order, version=version, reason=reason)
        try:
            decision = self.understand(order)
            plan.reason = f"{reason}; {decision.rationale}"
        except Exception:
            logger.exception("OpenRouter planner annotation failed")
        return plan

    def _invoke(self, *, system: str, user: str) -> dict:
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            api_key=self._settings.openrouter_api_key,
            base_url=self._settings.openrouter_base_url,
            model=self._settings.openrouter_model,
            temperature=0,
        )
        response = model.invoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        text = str(content).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)


def build_work_order_planner(settings: Settings) -> WorkOrderPlanner:
    wants_llm = settings.work_order_planner_mode == "llm" or (
        settings.work_order_planner_mode == "auto" and bool(settings.openrouter_api_key)
    )
    if wants_llm and settings.openrouter_api_key:
        return OpenRouterWorkOrderPlanner(settings)
    return DeterministicWorkOrderPlanner()
