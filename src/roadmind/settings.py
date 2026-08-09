from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    roadmind_env: Literal["local", "test", "production"] = "local"
    roadmind_log_level: str = "INFO"
    database_url: str | None = None
    redis_url: str | None = None
    mcp_gateway_url: str | None = None
    mcp_request_timeout_seconds: float = 5.0
    jwt_secret: str = "roadmind-dev-secret-change-me-32chars"
    jwt_ttl_minutes: int = 720
    cors_origins: str = (
        "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:80,http://localhost"
    )
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "nvidia/nemotron-nano-9b-v2:free"
    work_order_planner_mode: Literal["auto", "deterministic", "llm"] = Field(
        default="auto",
        validation_alias=AliasChoices("WORK_ORDER_PLANNER_MODE", "PARENT_MODE"),
    )
    assistant_mode: Literal["auto", "deterministic", "deep_agents"] = "auto"
    assistant_api_key: str | None = None
    assistant_base_url: str | None = None
    assistant_model: str | None = None
    demo_password: str = "roadmind123"

    @model_validator(mode="after")
    def reject_unsafe_production_secrets(self) -> Settings:
        if self.roadmind_env != "production":
            return self
        weak_jwt_secrets = {
            "roadmind-dev-secret-change-me-32chars",
            "replace-with-at-least-32-random-chars",
        }
        if (
            self.jwt_secret in weak_jwt_secrets
            or self.jwt_secret.startswith("replace-with")
            or len(self.jwt_secret) < 32
        ):
            raise ValueError("production JWT_SECRET must be a unique value of at least 32 chars")
        return self

    def validate_api_credentials(self) -> None:
        """Validate credentials used only by the business API's local demo identity store."""

        if self.roadmind_env != "production":
            return
        if (
            self.demo_password == "roadmind123"
            or self.demo_password.startswith("replace-with")
            or len(self.demo_password) < 12
        ):
            raise ValueError("production DEMO_PASSWORD must be a unique value of at least 12 chars")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def use_postgres(self) -> bool:
        return bool(self.database_url) and self.roadmind_env != "test"

    @property
    def use_redis(self) -> bool:
        return bool(self.redis_url) and self.roadmind_env != "test"

    @property
    def use_remote_mcp(self) -> bool:
        return bool(self.mcp_gateway_url) and self.roadmind_env != "test"

    @property
    def allow_header_auth(self) -> bool:
        return self.roadmind_env == "test"

    @property
    def resolved_assistant_api_key(self) -> str | None:
        return self.assistant_api_key or self.openrouter_api_key

    @property
    def resolved_assistant_base_url(self) -> str:
        return self.assistant_base_url or self.openrouter_base_url

    @property
    def resolved_assistant_model(self) -> str:
        return self.assistant_model or self.openrouter_model

    @property
    def use_deep_agents(self) -> bool:
        if self.assistant_mode == "deterministic":
            return False
        return bool(self.resolved_assistant_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
