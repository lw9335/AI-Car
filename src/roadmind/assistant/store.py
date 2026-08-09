from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Protocol

from roadmind.assistant.models import AssistantTurn


class ConversationNotFound(KeyError):
    pass


class ConversationStore(Protocol):
    def append(self, turn: AssistantTurn) -> None: ...

    def list(self, conversation_id: str, user_id: str) -> list[AssistantTurn]: ...


class InMemoryConversationStore:
    """Process-local adapter used until the Postgres conversation adapter is enabled."""

    def __init__(self) -> None:
        self._turns: dict[str, list[AssistantTurn]] = defaultdict(list)
        self._owners: dict[str, str] = {}
        self._lock = RLock()

    def append(self, turn: AssistantTurn) -> None:
        with self._lock:
            owner = self._owners.setdefault(turn.conversation_id, turn.user_id)
            if owner != turn.user_id:
                raise PermissionError("conversation belongs to another user")
            self._turns[turn.conversation_id].append(turn)

    def list(self, conversation_id: str, user_id: str) -> list[AssistantTurn]:
        with self._lock:
            owner = self._owners.get(conversation_id)
            if owner is None or owner != user_id:
                raise ConversationNotFound(conversation_id)
            return list(self._turns[conversation_id])
