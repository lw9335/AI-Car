from __future__ import annotations

import pytest

from roadmind.settings import Settings


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "jwt_secret": "roadmind-dev-secret-change-me-32chars",
                "demo_password": "unique-production-password",
            },
            "JWT_SECRET",
        ),
        (
            {
                "jwt_secret": "replace-with-at-least-32-random-chars",
                "demo_password": "unique-production-password",
            },
            "JWT_SECRET",
        ),
    ],
)
def test_production_rejects_unsafe_default_credentials(overrides, message):
    with pytest.raises(ValueError, match=message):
        Settings(roadmind_env="production", **overrides)


def test_local_mode_keeps_zero_config_developer_experience():
    settings = Settings(
        roadmind_env="local",
        jwt_secret="roadmind-dev-secret-change-me-32chars",
        demo_password="roadmind123",
    )

    assert settings.roadmind_env == "local"


@pytest.mark.parametrize("password", ["roadmind123", "replace-with-unique-password"])
def test_business_api_rejects_unsafe_production_demo_password(password):
    settings = Settings(
        roadmind_env="production",
        jwt_secret="unique-production-jwt-secret-with-32-chars",
        demo_password=password,
    )

    with pytest.raises(ValueError, match="DEMO_PASSWORD"):
        settings.validate_api_credentials()
