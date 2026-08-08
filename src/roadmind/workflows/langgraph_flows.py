from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ApprovalState(TypedDict, total=False):
    request: dict[str, Any]
    decision: dict[str, Any]
    approved: bool


def _human_gate(state: ApprovalState) -> ApprovalState:
    decision = interrupt(state["request"])
    return {"decision": decision, "approved": bool(decision.get("approved"))}


class NativeApprovalWorkflow:
    """Small, reusable proof of LangGraph checkpoint / interrupt / resume semantics."""

    def __init__(self) -> None:
        graph = StateGraph(ApprovalState)
        graph.add_node("human_gate", _human_gate)
        graph.add_edge(START, "human_gate")
        graph.add_edge("human_gate", END)
        self.graph = graph.compile(checkpointer=MemorySaver())

    @staticmethod
    def config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    def start(self, thread_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self.graph.invoke({"request": request}, config=self.config(thread_id))

    def resume(self, thread_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        return self.graph.invoke(Command(resume=decision), config=self.config(thread_id))


class FulfillmentState(TypedDict, total=False):
    service_request_id: str
    dispatch_candidates: list[dict[str, Any]]
    parts_candidates: list[dict[str, Any]]
    dispatch_ready: bool
    parts_ready: bool
    joined: bool


def build_parallel_fulfillment_graph(
    dispatch_node: Any,
    parts_node: Any,
):
    """Fan out dispatch and parts preparation and join only when both return."""

    def join(state: FulfillmentState) -> FulfillmentState:
        return {
            "dispatch_ready": bool(state.get("dispatch_candidates")),
            "parts_ready": bool(state.get("parts_candidates")),
            "joined": bool(state.get("dispatch_candidates"))
            and bool(state.get("parts_candidates")),
        }

    graph = StateGraph(FulfillmentState)
    graph.add_node("dispatch_candidates", dispatch_node)
    graph.add_node("parts_candidates", parts_node)
    graph.add_node("join", join)
    graph.add_edge(START, "dispatch_candidates")
    graph.add_edge(START, "parts_candidates")
    graph.add_edge(["dispatch_candidates", "parts_candidates"], "join")
    graph.add_edge("join", END)
    return graph.compile()


class ReplanState(TypedDict, total=False):
    old_plan_version: int
    new_plan_version: int
    released_resource: str | None
    released_parts: list[str]
    reason: str
    frozen: bool
    compensated: bool


def build_mismatch_replan_graph(freeze_node: Any, compensate_node: Any):
    graph = StateGraph(ReplanState)
    graph.add_node("freeze_old_plan", freeze_node)
    graph.add_node("compensate_fulfillment", compensate_node)
    graph.add_node(
        "increment_plan",
        lambda state: {
            "new_plan_version": state["old_plan_version"] + 1,
            "reason": state["reason"],
        },
    )
    graph.add_edge(START, "freeze_old_plan")
    graph.add_edge("freeze_old_plan", "compensate_fulfillment")
    graph.add_edge("compensate_fulfillment", "increment_plan")
    graph.add_edge("increment_plan", END)
    return graph.compile()
