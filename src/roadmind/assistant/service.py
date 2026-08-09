from __future__ import annotations

from uuid import uuid4

from langchain_openai import ChatOpenAI

from roadmind.application.service import RoadMindService
from roadmind.assistant.models import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantTurn,
    ConversationView,
)
from roadmind.assistant.runtime import (
    AssistantRuntime,
    DeepAgentsAssistantRuntime,
    DeterministicAssistantRuntime,
    classify_intent,
)
from roadmind.assistant.store import ConversationStore, InMemoryConversationStore
from roadmind.assistant.supervisor import BoundBusinessAgentTools, BusinessAgentSupervisor
from roadmind.domain.auth import Principal, require_scope
from roadmind.mcp.gateway import ToolGateway
from roadmind.settings import Settings


class EnterpriseAssistantService:
    def __init__(
        self,
        *,
        runtime: AssistantRuntime,
        gateway: ToolGateway,
        conversations: ConversationStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._gateway = gateway
        self._conversations = conversations or InMemoryConversationStore()

    def chat(self, request: AssistantChatRequest, principal: Principal) -> AssistantChatResponse:
        require_scope(principal, "assistant:chat")
        conversation_id = request.conversation_id or f"conv_{uuid4().hex[:16]}"
        self._conversations.append(
            AssistantTurn(
                conversation_id=conversation_id,
                user_id=principal.user_id,
                role="user",
                content=request.message,
            )
        )
        runtime_result = self._runtime.respond(
            request,
            principal,
            conversation_id=conversation_id,
        )
        assistant_turn = AssistantTurn(
            conversation_id=conversation_id,
            user_id=principal.user_id,
            role="assistant",
            content=runtime_result.content,
        )
        self._conversations.append(assistant_turn)
        capabilities = [item["name"] for item in self._gateway.list_tools(principal)]
        capabilities.extend(BoundBusinessAgentTools.COMMANDS)
        intent = classify_intent(request.message)
        return AssistantChatResponse(
            conversation_id=conversation_id,
            turn_id=assistant_turn.turn_id,
            mode=self._runtime.mode,  # type: ignore[arg-type]
            intent=intent,
            content=runtime_result.content,
            available_capabilities=capabilities,
            executed_actions=runtime_result.executions,
            requires_follow_up=(
                not runtime_result.executions and intent in {"office", "general_assistance"}
            ),
        )

    def conversation(self, conversation_id: str, principal: Principal) -> ConversationView:
        require_scope(principal, "assistant:chat")
        return ConversationView(
            conversation_id=conversation_id,
            turns=self._conversations.list(conversation_id, principal.user_id),
        )


def build_assistant_service(
    settings: Settings,
    gateway: ToolGateway,
    roadmind_service: RoadMindService,
) -> EnterpriseAssistantService:
    if settings.assistant_mode == "deep_agents" and not settings.resolved_assistant_api_key:
        raise ValueError(
            "ASSISTANT_MODE=deep_agents requires ASSISTANT_API_KEY or OPENROUTER_API_KEY"
        )
    supervisor = BusinessAgentSupervisor(roadmind_service)
    if settings.use_deep_agents:
        model = ChatOpenAI(
            api_key=settings.resolved_assistant_api_key,
            base_url=settings.resolved_assistant_base_url,
            model=settings.resolved_assistant_model,
            temperature=0,
        )
        runtime: AssistantRuntime = DeepAgentsAssistantRuntime(
            model=model,
            gateway=gateway,
            supervisor=supervisor,
        )
    else:
        runtime = DeterministicAssistantRuntime(gateway, supervisor)
    return EnterpriseAssistantService(runtime=runtime, gateway=gateway)
