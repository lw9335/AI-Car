from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roadmind.domain.auth import Principal
from roadmind.domain.models import Role, WorkOrder, WorkOrderStatus


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    display_name: str
    aliases: tuple[str, ...]
    unit: str
    description: str


METRICS = [
    MetricDefinition("workorder_count", "工单量", ("工单数", "报修量"), "单", "范围内工单总数"),
    MetricDefinition("closure_rate", "闭环率", ("结案率", "完成率"), "%", "已结案工单占比"),
    MetricDefinition(
        "first_time_fix_rate", "首次修复率", ("一次修复率",), "%", "未发生改诊的结案工单占比"
    ),
    MetricDefinition(
        "sla_compliance", "SLA 达成率", ("及时率",), "%", "演示环境用 24 小时窗口近似"
    ),
    MetricDefinition(
        "parts_fill_rate", "配件满足率", ("配件齐套率",), "%", "已预占配件的履约工单占比"
    ),
]


class MetricNotAllowed(ValueError):
    pass


class OperationsAgent:
    """Semantic metrics only: no model-generated free-form SQL enters the data plane."""

    def answer(
        self,
        question: str,
        orders: list[WorkOrder],
        *,
        principal: Principal,
        scenario_delta: float | None = None,
    ) -> dict[str, Any]:
        metric = self._resolve_metric(question)
        scoped = self._apply_abac(orders, principal)
        value = self._calculate(metric.metric_id, scoped)
        fact = {
            "metric_id": metric.metric_id,
            "display_name": metric.display_name,
            "value": value,
            "unit": metric.unit,
            "sample_size": len(scoped),
            "scope": principal.region,
        }
        result: dict[str, Any] = {
            "fact": fact,
            "inference": self._inference(metric.metric_id, value, scoped),
            "recommendation": self._recommend(metric.metric_id, value),
            "query_template": f"metrics.run_template(metric_id='{metric.metric_id}')",
        }
        if scenario_delta is not None:
            result["scenario"] = {
                "label": "what_if_not_fact",
                "assumption": f"输入变化 {scenario_delta:+.1f}%",
                "projected_value": round(value * (1 + scenario_delta / 100), 2),
                "warning": "情景模拟结果，不得当作已发生事实",
            }
        return result

    @staticmethod
    def _resolve_metric(question: str) -> MetricDefinition:
        lowered = question.lower()
        for metric in METRICS:
            if metric.display_name.lower() in lowered or any(
                alias in lowered for alias in metric.aliases
            ):
                return metric
        raise MetricNotAllowed("question does not map to a whitelisted metric_id")

    @staticmethod
    def _apply_abac(orders: list[WorkOrder], principal: Principal) -> list[WorkOrder]:
        if principal.role == Role.ADMIN:
            return orders
        return [order for order in orders if principal.region in {"south_china", order.location}]

    @staticmethod
    def _calculate(metric_id: str, orders: list[WorkOrder]) -> float:
        if metric_id == "workorder_count":
            return float(len(orders))
        if not orders:
            return 0.0
        if metric_id == "closure_rate":
            return round(
                100 * sum(o.status == WorkOrderStatus.CLOSED for o in orders) / len(orders), 2
            )
        if metric_id == "first_time_fix_rate":
            closed = [o for o in orders if o.status == WorkOrderStatus.CLOSED]
            return (
                round(100 * sum(o.replan_count == 0 for o in closed) / len(closed), 2)
                if closed
                else 0.0
            )
        if metric_id == "sla_compliance":
            return round(100 * sum(not o.degraded_mode for o in orders) / len(orders), 2)
        if metric_id == "parts_fill_rate":
            return round(100 * sum(bool(o.reserved_part_codes) for o in orders) / len(orders), 2)
        raise MetricNotAllowed(metric_id)

    @staticmethod
    def _inference(metric_id: str, value: float, orders: list[WorkOrder]) -> dict[str, Any]:
        return {
            "label": "hypothesis_not_fact",
            "text": f"{metric_id} 当前值为 {value}，可能受样本量 {len(orders)} 与进行中工单影响。",
            "confidence": 0.58,
        }

    @staticmethod
    def _recommend(metric_id: str, value: float) -> dict[str, Any]:
        return {
            "status": "pending_approval",
            "owner": "区域运营负责人",
            "action": f"针对 {metric_id} 建立分品牌周度复盘并核查异常工单",
            "target": round(min(100.0, value + 5), 2),
            "observation_window_days": 28,
            "stop_condition": "连续两周无改善或产生安全/合规风险",
        }
