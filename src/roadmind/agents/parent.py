"""Compatibility imports for the former Parent Agent module.

The interactive supervisor lives in :mod:`roadmind.assistant`. New code must import the
auditable work-order planner from :mod:`roadmind.workflows.task_planner`.
"""

from roadmind.workflows.task_planner import (
    DeterministicWorkOrderPlanner,
    OpenRouterWorkOrderPlanner,
    PlanningDecision,
    WorkOrderPlanner,
    build_work_order_planner,
)

ParentDecision = PlanningDecision
ParentAgent = WorkOrderPlanner
DeterministicParentAgent = DeterministicWorkOrderPlanner
OpenRouterParentAgent = OpenRouterWorkOrderPlanner
build_parent_agent = build_work_order_planner

__all__ = [
    "DeterministicParentAgent",
    "DeterministicWorkOrderPlanner",
    "OpenRouterParentAgent",
    "OpenRouterWorkOrderPlanner",
    "ParentAgent",
    "ParentDecision",
    "PlanningDecision",
    "WorkOrderPlanner",
    "build_parent_agent",
    "build_work_order_planner",
]
