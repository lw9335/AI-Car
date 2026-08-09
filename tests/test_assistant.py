from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from roadmind.assistant.main import create_assistant_app
from roadmind.assistant.models import AssistantChatRequest
from roadmind.assistant.runtime import DeepAgentsAssistantRuntime
from roadmind.assistant.service import build_assistant_service
from roadmind.assistant.supervisor import BusinessAgentSupervisor
from roadmind.domain.auth import Principal
from roadmind.domain.models import Role
from roadmind.settings import Settings


def test_standalone_assistant_harness_health_and_chat():
    with TestClient(create_assistant_app()) as assistant_client:
        health = assistant_client.get("/health")
        response = assistant_client.post(
            "/v1/chat",
            json={"message": "帮我查询车辆维修情况"},
            headers={"X-Role": "information_officer", "X-User-Id": "info-1"},
        )

    assert health.status_code == 200
    assert health.json()["service"] == "roadmind-enterprise-assistant"
    assert response.status_code == 200
    assert response.json()["intent"] == "after_sales"


def test_standalone_assistant_understands_english_operations_intent():
    with TestClient(create_assistant_app()) as assistant_client:
        response = assistant_client.post(
            "/v1/chat",
            json={"message": "Analyze the weekly operations report"},
            headers={"X-Role": "operations", "X-User-Id": "ops-1"},
        )

    assert response.status_code == 200
    assert response.json()["intent"] == "operations"


def test_assistant_chat_creates_conversation_and_history(client):
    headers = {"X-Role": "operations", "X-User-Id": "ops-1"}
    response = client.post(
        "/api/v1/assistant/chat",
        json={"message": "请帮我分析今天的运营报表"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "deterministic"
    assert body["intent"] == "operations"
    assert body["conversation_id"].startswith("conv_")
    assert "metrics.run_template" in body["available_capabilities"]

    history = client.get(
        f"/api/v1/assistant/conversations/{body['conversation_id']}",
        headers=headers,
    )
    assert history.status_code == 200
    assert [turn["role"] for turn in history.json()["turns"]] == ["user", "assistant"]


def test_assistant_conversation_is_isolated_by_user(client):
    created = client.post(
        "/api/v1/assistant/chat",
        json={"message": "查询维修工单"},
        headers={"X-Role": "information_officer", "X-User-Id": "owner"},
    ).json()

    denied = client.get(
        f"/api/v1/assistant/conversations/{created['conversation_id']}",
        headers={"X-Role": "information_officer", "X-User-Id": "other"},
    )
    assert denied.status_code == 404


def test_deep_agents_runtime_passes_thread_and_exposes_supervisor_tools(service):
    captured = {}

    class FakeGraph:
        def invoke(self, payload, config=None, *, context=None, **_kwargs):
            captured["payload"] = payload
            captured["config"] = config
            captured["context"] = context
            return {"messages": [SimpleNamespace(content="done")]}

    def graph_factory(**kwargs):
        captured["tools"] = kwargs["tools"]
        captured["subagents"] = kwargs["subagents"]
        captured["system_prompt"] = kwargs["system_prompt"]
        captured["checkpointer"] = kwargs["checkpointer"]
        captured["context_schema"] = kwargs["context_schema"]
        return FakeGraph()

    supervisor = BusinessAgentSupervisor(service)
    runtime = DeepAgentsAssistantRuntime(
        model=object(),
        gateway=service.gateway,
        supervisor=supervisor,
        graph_factory=graph_factory,
    )
    admin = Principal(user_id="admin", role=Role.ADMIN)
    result = runtime.respond(
        AssistantChatRequest(message="查看能力"),
        admin,
        conversation_id="conv-test",
    )

    assert result.content == "done"
    assert captured["config"]["configurable"]["thread_id"] == "conv-test"
    assert captured["context_schema"] is not None
    assert captured["context"].principal == admin
    assert captured["context"].conversation_id == "conv-test"
    tool_names = {tool.name for tool in captured["tools"]}
    assert tool_names == {
        "list_mcp_capabilities",
        "call_read_mcp_tool",
        "list_work_orders",
        "get_work_order",
    }
    subagents = {item["name"]: item for item in captured["subagents"]}
    assert set(subagents) == {
        "diagnosis-agent",
        "dispatch-agent",
        "parts-agent",
        "operations-agent",
    }
    assert {tool.name for tool in subagents["diagnosis-agent"]["tools"]} >= {
        "create_work_order",
        "diagnosis_agent_run",
        "diagnosis_agent_confirm",
        "request_service_closure",
    }
    assert {tool.name for tool in subagents["dispatch-agent"]["tools"]} == {
        "get_work_order",
        "dispatch_agent_approve",
    }
    assert {tool.name for tool in subagents["parts-agent"]["tools"]} == {
        "get_work_order",
        "parts_agent_reserve",
    }
    assert {tool.name for tool in subagents["operations-agent"]["tools"]} >= {
        "operations_agent_query",
        "call_read_mcp_tool",
    }
    assert "唯一的持续对话入口" in captured["system_prompt"]
    assert "不得把初诊当作专家确诊" in subagents["diagnosis-agent"]["system_prompt"]

    from langchain.tools import ToolRuntime

    from roadmind.assistant.runtime import AssistantToolContext

    call_tool = next(tool for tool in captured["tools"] if tool.name == "call_read_mcp_tool")
    tool_runtime = ToolRuntime(
        state={},
        context=AssistantToolContext(
            principal=admin,
            conversation_id="conv-test",
            gateway=service.gateway,
            bound=supervisor.bind(admin),
        ),
        config={},
        stream_writer=lambda *_args, **_kwargs: None,
        tool_call_id="test-call",
        store=None,
    )
    with pytest.raises(PermissionError, match="read-only"):
        call_tool.invoke(
            {
                "tool_name": "inventory.reserve",
                "arguments": {"service_request_id": "sr-1", "part_codes": []},
                "runtime": tool_runtime,
            }
        )


def test_deep_agents_runtime_disables_default_general_purpose_subagent(service, monkeypatch):
    import deepagents

    captured = {}

    class FakeGraph:
        pass

    def fake_register(key, profile):
        captured["profile_key"] = key
        captured["profile"] = profile

    def fake_create_deep_agent(**kwargs):
        captured["subagents"] = kwargs["subagents"]
        return FakeGraph()

    monkeypatch.setattr(deepagents, "register_harness_profile", fake_register)
    monkeypatch.setattr(deepagents, "create_deep_agent", fake_create_deep_agent)

    DeepAgentsAssistantRuntime(
        model=object(),
        gateway=service.gateway,
        supervisor=BusinessAgentSupervisor(service),
    )

    assert captured["profile_key"] == "openai"
    assert captured["profile"].general_purpose_subagent.enabled is False
    assert {item["name"] for item in captured["subagents"]} == {
        "diagnosis-agent",
        "dispatch-agent",
        "parts-agent",
        "operations-agent",
    }


def test_explicit_deep_agents_mode_requires_model_credentials(service):
    settings = Settings(
        roadmind_env="test",
        assistant_mode="deep_agents",
        assistant_api_key=None,
        openrouter_api_key=None,
    )

    with pytest.raises(ValueError, match="ASSISTANT_API_KEY"):
        build_assistant_service(settings, service.gateway, service)


def test_interactive_supervisor_controls_four_agents_through_shared_service(client, diesel_request):
    headers = {"X-Role": "admin", "X-User-Id": "supervisor-admin"}
    created = client.post(
        "/api/v1/work-orders",
        json=diesel_request.model_dump(mode="json"),
        headers=headers,
    )
    assert created.status_code == 201
    order_id = created.json()["service_request_id"]

    diagnosis = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "请让诊断 Agent 分析这个工单",
            "context": {
                "command": "diagnosis.run",
                "arguments": {"order_id": order_id},
            },
        },
        headers=headers,
    )
    assert diagnosis.status_code == 200
    diagnosis_body = diagnosis.json()
    assert diagnosis_body["executed_actions"][0]["capability"] == "diagnosis_agent"
    diagnosed_order = diagnosis_body["executed_actions"][0]["result"]
    diagnosis_id = diagnosed_order["diagnosis"]["diagnosis_id"]

    confirmed = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "我确认诊断，请继续让调度和配件 Agent 准备候选",
            "confirmed_actions": ["diagnosis.confirm"],
            "context": {
                "command": "diagnosis.confirm",
                "arguments": {
                    "order_id": order_id,
                    "diagnosis_id": diagnosis_id,
                    "approved": True,
                    "confirmed_code": "P20EE",
                },
            },
        },
        headers=headers,
    )
    assert confirmed.status_code == 200
    fulfillment = confirmed.json()["executed_actions"][0]["result"]
    assert fulfillment["dispatch_candidates"]
    assert fulfillment["parts_candidates"]

    blocked_parts = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "预留第一个配件",
            "context": {
                "command": "parts.reserve",
                "arguments": {
                    "order_id": order_id,
                    "part_codes": [fulfillment["parts_candidates"][0]["part_code"]],
                },
            },
        },
        headers=headers,
    )
    assert blocked_parts.status_code == 422
    assert "explicit confirmation" in blocked_parts.json()["detail"]

    dispatch_approval = next(
        item for item in fulfillment["approvals"] if item["action"] == "dispatch.assign"
    )
    dispatched = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "确认采用第一个调度候选",
            "confirmed_actions": ["dispatch.approve"],
            "context": {
                "command": "dispatch.approve",
                "arguments": {
                    "order_id": order_id,
                    "resource_id": fulfillment["dispatch_candidates"][0]["resource_id"],
                    "approval_token": dispatch_approval["token"],
                },
            },
        },
        headers=headers,
    )
    assert dispatched.status_code == 200
    assert dispatched.json()["executed_actions"][0]["capability"] == "dispatch_agent"

    reserved = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "确认预留第一个配件候选",
            "confirmed_actions": ["parts.reserve"],
            "context": {
                "command": "parts.reserve",
                "arguments": {
                    "order_id": order_id,
                    "part_codes": [fulfillment["parts_candidates"][0]["part_code"]],
                },
            },
        },
        headers=headers,
    )
    assert reserved.status_code == 200
    assert reserved.json()["executed_actions"][0]["capability"] == "parts_agent"

    started = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "我确认现场开工",
            "confirmed_actions": ["service.start"],
            "context": {
                "command": "service.start",
                "arguments": {"order_id": order_id},
            },
        },
        headers=headers,
    )
    assert started.status_code == 200
    assert started.json()["executed_actions"][0]["result"]["status"] == "in_service"

    closure = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "维修已经完成，我确认提交结案",
            "confirmed_actions": ["service.close"],
            "context": {
                "command": "service.close",
                "arguments": {
                    "order_id": order_id,
                    "resolution": "更换下游 NOx 传感器并完成路试验证",
                    "actual_part_codes": [fulfillment["parts_candidates"][0]["part_code"]],
                    "customer_rating": 5,
                },
            },
        },
        headers=headers,
    )
    assert closure.status_code == 200
    closure_order = closure.json()["executed_actions"][0]["result"]
    closure_approval = next(
        item for item in closure_order["approvals"] if item["action"] == "service.close"
    )

    closed = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "我确认结案材料完整，同意关闭工单",
            "confirmed_actions": ["service.close_approve"],
            "context": {
                "command": "service.close_approve",
                "arguments": {
                    "order_id": order_id,
                    "approval_token": closure_approval["token"],
                    "approved": True,
                    "comment": "结案证据完整",
                },
            },
        },
        headers=headers,
    )
    assert closed.status_code == 200
    assert closed.json()["executed_actions"][0]["result"]["status"] == "closed"

    operations = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "让运营 Agent 汇总当前工单",
            "context": {
                "command": "operations.query",
                "arguments": {"question": "当前工单量是多少"},
            },
        },
        headers=headers,
    )
    assert operations.status_code == 200
    assert operations.json()["executed_actions"][0]["capability"] == "operations_agent"

    manually_read = client.get(f"/api/v1/work-orders/{order_id}", headers=headers)
    assert manually_read.status_code == 200
    assert manually_read.json()["status"] == "closed"
