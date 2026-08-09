from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain.tools import ToolRuntime, tool
from langgraph.checkpoint.memory import MemorySaver

from roadmind.assistant.models import AssistantChatRequest, AssistantExecution
from roadmind.assistant.prompts import (
    BUSINESS_SUBAGENT_DEFINITIONS,
    SUPERVISOR_SYSTEM_PROMPT,
    SUPERVISOR_TOOL_NAMES,
)
from roadmind.assistant.supervisor import BusinessAgentSupervisor
from roadmind.domain.auth import Principal
from roadmind.mcp.gateway import ToolGateway

SYSTEM_PROMPT = SUPERVISOR_SYSTEM_PROMPT


@dataclass
class AssistantToolContext:
    """Per-invoke context injected into @tool handlers via ToolRuntime."""

    principal: Principal
    conversation_id: str
    gateway: Any
    bound: Any


@dataclass
class AssistantRuntimeResult:
    content: str
    executions: list[AssistantExecution] = field(default_factory=list)


class AssistantRuntime(Protocol):
    mode: str

    def respond(
        self,
        request: AssistantChatRequest,
        principal: Principal,
        *,
        conversation_id: str,
    ) -> AssistantRuntimeResult: ...


def classify_intent(message: str) -> str:
    lowered = message.lower()
    intent_keywords = (
        (
            "after_sales",
            (
                "工单",
                "维修",
                "故障",
                "车辆",
                "诊断",
                "配件",
                "派工",
                "work order",
                "repair",
                "fault",
                "vehicle",
                "diagnosis",
                "parts",
                "dispatch",
            ),
        ),
        (
            "operations",
            (
                "运营",
                "指标",
                "报表",
                "数据",
                "分析",
                "operations",
                "metric",
                "report",
                "analytics",
            ),
        ),
        (
            "office",
            (
                "会议",
                "日程",
                "邮件",
                "文档",
                "通知",
                "待办",
                "meeting",
                "calendar",
                "email",
                "document",
                "notification",
                "todo",
            ),
        ),
        (
            "knowledge",
            (
                "制度",
                "手册",
                "知识",
                "案例",
                "怎么做",
                "policy",
                "manual",
                "knowledge",
                "case",
                "how to",
            ),
        ),
    )
    for intent, keywords in intent_keywords:
        if any(keyword in lowered for keyword in keywords):
            return intent
    return "general_assistance"


def _tool_context(runtime: ToolRuntime) -> AssistantToolContext:
    """Read the request-scoped assistant context injected by Deep Agents."""

    context = runtime.context
    if not isinstance(context, AssistantToolContext):
        raise TypeError("assistant tools require AssistantToolContext")
    return context


@tool
def list_mcp_capabilities(runtime: ToolRuntime) -> str:
    """List MCP capabilities available to the current authenticated user."""

    ctx = _tool_context(runtime)
    return json.dumps(
        ctx.gateway.list_tools(ctx.principal),
        ensure_ascii=False,
        default=str,
    )


@tool
def call_read_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any],
    runtime: ToolRuntime,
    service_request_id: str = "assistant",
) -> str:
    """Call one discovered read-only MCP tool with structured arguments."""

    ctx = _tool_context(runtime)
    allowed = {
        item["name"]: item
        for item in ctx.gateway.list_tools(ctx.principal)
        if item.get("risk") == "read"
    }
    if tool_name not in allowed:
        raise PermissionError("only discovered read-only MCP tools are callable")
    result = ctx.gateway.invoke(
        tool_name,
        arguments,
        principal=ctx.principal,
        service_request_id=service_request_id or ctx.conversation_id,
    )
    return json.dumps(result, ensure_ascii=False, default=str)


@tool
def list_work_orders(runtime: ToolRuntime) -> dict[str, Any]:
    """List work orders visible to the current user."""

    return _tool_context(runtime).bound.list_work_orders()


@tool
def get_work_order(order_id: str, runtime: ToolRuntime) -> dict[str, Any]:
    """Get one work order, including current state, candidates and pending approvals."""

    return _tool_context(runtime).bound.get_work_order(order_id)


@tool
def create_work_order(
    request: dict[str, Any],
    runtime: ToolRuntime,
) -> dict[str, Any]:
    """Create a work order from a complete ServiceRequestCreate object."""

    return _tool_context(runtime).bound.create_work_order(request)


@tool
def diagnosis_agent_run(order_id: str, runtime: ToolRuntime) -> dict[str, Any]:
    """Run the diagnosis agent for a triaged or rediagnosis-required work order."""

    return _tool_context(runtime).bound.diagnosis_agent_run(order_id)


@tool
def diagnosis_agent_confirm(
    order_id: str,
    diagnosis_id: str,
    approved: bool,
    runtime: ToolRuntime,
    confirmed_code: str = "",
    comment: str = "",
) -> dict[str, Any]:
    """Record an expert's explicit diagnosis decision and start fulfillment when approved."""

    return _tool_context(runtime).bound.diagnosis_agent_confirm(
        order_id,
        diagnosis_id,
        approved,
        confirmed_code=confirmed_code,
        comment=comment,
    )


@tool
def dispatch_agent_approve(
    order_id: str,
    resource_id: str,
    approval_token: str,
    runtime: ToolRuntime,
) -> dict[str, Any]:
    """Approve the dispatch agent candidate selected by a human dispatcher."""

    return _tool_context(runtime).bound.dispatch_agent_approve(
        order_id,
        resource_id,
        approval_token,
    )


@tool
def parts_agent_reserve(
    order_id: str,
    part_codes: list[str],
    runtime: ToolRuntime,
    bring_both: bool = False,
) -> dict[str, Any]:
    """Reserve VIN-compatible parts after an explicit human confirmation."""

    return _tool_context(runtime).bound.parts_agent_reserve(
        order_id,
        part_codes,
        bring_both=bring_both,
    )


@tool
def operations_agent_query(
    question: str,
    runtime: ToolRuntime,
    scope: str = "all",
    scenario_delta: float | None = None,
) -> dict[str, Any]:
    """Ask the operations agent for metrics, analysis or a scenario simulation."""

    return _tool_context(runtime).bound.operations_agent_query(
        question,
        scope=scope,
        scenario_delta=scenario_delta,
    )


@tool
def start_field_service(order_id: str, runtime: ToolRuntime) -> dict[str, Any]:
    """Start on-site service after dispatch and parts fulfillment are ready."""

    return _tool_context(runtime).bound.start_field_service(order_id)


@tool
def diagnosis_agent_report_mismatch(
    order_id: str,
    actual_code: str,
    evidence: str,
    runtime: ToolRuntime,
) -> dict[str, Any]:
    """Report field evidence that conflicts with the diagnosis and trigger compensation."""

    return _tool_context(runtime).bound.diagnosis_agent_report_mismatch(
        order_id,
        actual_code,
        evidence,
    )


@tool
def resume_manual_takeover(order_id: str, runtime: ToolRuntime) -> dict[str, Any]:
    """Resume a manually reviewed work order in degraded rediagnosis mode."""

    return _tool_context(runtime).bound.resume_manual_takeover(order_id)


@tool
def request_service_closure(
    order_id: str,
    resolution: str,
    actual_part_codes: list[str],
    customer_rating: int,
    runtime: ToolRuntime,
) -> dict[str, Any]:
    """Submit the field-service result for expert closure approval."""

    return _tool_context(runtime).bound.request_service_closure(
        order_id,
        resolution,
        actual_part_codes,
        customer_rating,
    )


@tool
def approve_service_closure(
    order_id: str,
    approval_token: str,
    approved: bool,
    runtime: ToolRuntime,
    comment: str = "",
) -> dict[str, Any]:
    """Record an expert's explicit closure decision using the pending approval token."""

    return _tool_context(runtime).bound.approve_service_closure(
        order_id,
        approval_token,
        approved,
        comment=comment,
    )


ASSISTANT_TOOLS = [
    list_mcp_capabilities,
    call_read_mcp_tool,
    list_work_orders,
    get_work_order,
    create_work_order,
    diagnosis_agent_run,
    diagnosis_agent_confirm,
    dispatch_agent_approve,
    parts_agent_reserve,
    operations_agent_query,
    start_field_service,
    diagnosis_agent_report_mismatch,
    resume_manual_takeover,
    request_service_closure,
    approve_service_closure,
]


def build_business_subagents() -> list[dict[str, Any]]:
    """Build Deep Agents subagent specs from declarative least-privilege contracts."""

    tools_by_name = {item.name: item for item in ASSISTANT_TOOLS}
    specs: list[dict[str, Any]] = []
    for definition in BUSINESS_SUBAGENT_DEFINITIONS:
        missing = set(definition.tool_names) - tools_by_name.keys()
        if missing:
            raise RuntimeError(
                f"subagent {definition.name} references unknown tools: {sorted(missing)}"
            )
        specs.append(
            {
                "name": definition.name,
                "description": definition.description,
                "system_prompt": definition.system_prompt,
                "tools": [tools_by_name[name] for name in definition.tool_names],
            }
        )
    return specs


def supervisor_tools() -> list[Any]:
    """Expose only conversational/read tools directly to the supervisor."""

    tools_by_name = {item.name: item for item in ASSISTANT_TOOLS}
    return [tools_by_name[name] for name in SUPERVISOR_TOOL_NAMES]


class DeterministicAssistantRuntime:
    """Offline supervisor supporting explicit structured commands without an LLM."""

    mode = "deterministic"

    def __init__(self, gateway: ToolGateway, supervisor: BusinessAgentSupervisor) -> None:
        self._gateway = gateway
        self._supervisor = supervisor

    def respond(
        self,
        request: AssistantChatRequest,
        principal: Principal,
        *,
        conversation_id: str,
    ) -> AssistantRuntimeResult:
        bound = self._supervisor.bind(
            principal,
            confirmed_actions=set(request.confirmed_actions),
        )
        command = request.context.get("command")
        if command:
            arguments = request.context.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ValueError("assistant command arguments must be an object")
            bound.execute_command(str(command), arguments)
            return AssistantRuntimeResult(
                content=f"已通过交互式总控执行 {command}，结果已写入共享业务状态。",
                executions=list(bound.executions),
            )

        intent = classify_intent(request.message)
        capabilities = self._gateway.list_tools(principal)
        categories = sorted({item["name"].split(".", 1)[0] for item in capabilities})
        if intent == "after_sales":
            content = (
                "我已识别为售后服务任务。总控可以调用诊断、调度、配件和运营 Agent；"
                "请补充工单编号或完整建单信息。确认诊断、派工和配件预留仍会进入人工确认门禁。"
            )
        elif intent == "operations":
            content = "我已识别为运营分析任务，请补充指标、时间范围和区域范围。"
        elif intent == "office":
            content = (
                "我已识别为日常办公任务。目前办公类 MCP 服务尚未注册；"
                "接入邮件、日历和文档服务后即可由总控统一执行。"
            )
        else:
            content = "我可以继续拆解这个任务。当前 MCP 能力域包括：" + "、".join(categories)
        return AssistantRuntimeResult(content=content)


class DeepAgentsAssistantRuntime:
    """Interactive Deep Agents supervisor over business agents and MCP tools."""

    mode = "deep_agents"

    def __init__(
        self,
        *,
        model: Any,
        gateway: ToolGateway,
        supervisor: BusinessAgentSupervisor,
        graph_factory: Callable[..., Any] | None = None,
    ) -> None:
        if graph_factory is None:
            from deepagents import (
                GeneralPurposeSubagentProfile,
                HarnessProfile,
                create_deep_agent,
                register_harness_profile,
            )

            # ChatOpenAI-compatible endpoints resolve to the ``openai`` provider in
            # Deep Agents. RoadMind has four explicit business subagents, so the
            # framework's fifth, unrestricted general-purpose subagent must not be
            # added to the supervisor at graph-construction time.
            register_harness_profile(
                "openai",
                HarnessProfile(
                    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
                ),
            )

            graph_factory = create_deep_agent
        self._model = model
        self._gateway = gateway
        self._supervisor = supervisor
        self._graph_factory = graph_factory
        self._checkpointer = MemorySaver()
        self._graph = self._graph_factory(
            model=self._model,
            tools=supervisor_tools(),
            system_prompt=SYSTEM_PROMPT,
            subagents=build_business_subagents(),
            checkpointer=self._checkpointer,
            context_schema=AssistantToolContext,
            name="roadmind-enterprise-supervisor",
        )

    def respond(
        self,
        request: AssistantChatRequest,
        principal: Principal,
        *,
        conversation_id: str,
    ) -> AssistantRuntimeResult:
        bound = self._supervisor.bind(
            principal,
            confirmed_actions=set(request.confirmed_actions),
        )
        context = AssistantToolContext(
            principal=principal,
            conversation_id=conversation_id,
            gateway=self._gateway,
            bound=bound,
        )
        result = self._graph.invoke(
            {"messages": [{"role": "user", "content": request.message}]},
            config={"configurable": {"thread_id": conversation_id}},
            context=context,
        )
        messages = result.get("messages") or []
        if not messages:
            raise RuntimeError("Deep Agents returned no assistant message")
        content = getattr(messages[-1], "content", messages[-1])
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        return AssistantRuntimeResult(content=str(content), executions=list(bound.executions))
