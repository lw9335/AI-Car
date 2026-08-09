from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from roadmind.domain.models import utc_now


class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)
    conversation_id: str | None = Field(default=None, max_length=128)
    context: dict[str, Any] = Field(default_factory=dict)
    confirmed_actions: list[str] = Field(default_factory=list)


class AssistantExecution(BaseModel):
    capability: str
    operation: str
    result: dict[str, Any]


class AssistantTurn(BaseModel):
    turn_id: str = Field(default_factory=lambda: f"turn_{uuid4().hex[:12]}")
    conversation_id: str
    user_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class AssistantChatResponse(BaseModel):
    conversation_id: str
    turn_id: str
    mode: Literal["deterministic", "deep_agents"]
    intent: str
    content: str
    available_capabilities: list[str] = Field(default_factory=list)
    executed_actions: list[AssistantExecution] = Field(default_factory=list)
    requires_follow_up: bool = False


class ConversationView(BaseModel):
    conversation_id: str
    turns: list[AssistantTurn]
