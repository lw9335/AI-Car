from __future__ import annotations

import asyncio
import json

from fastapi import Request

from roadmind.domain.auth import Principal
from roadmind.domain.models import OpsQuery, Role
from roadmind.main import create_app
from roadmind.mcp.gateway import CircuitOpen, RateLimitExceeded


def test_operations_separates_fact_inference_recommendation_and_scenario(
    service, admin, diesel_request
):
    service.create_request(diesel_request, admin)
    ops = Principal(user_id="ops", role=Role.OPERATIONS)
    result = service.query_operations(OpsQuery(question="当前工单量是多少", scenario_delta=10), ops)
    assert result["fact"]["metric_id"] == "workorder_count"
    assert result["inference"]["label"] == "hypothesis_not_fact"
    assert result["recommendation"]["status"] == "pending_approval"
    assert result["scenario"]["label"] == "what_if_not_fact"
    assert "metrics.run_template" in result["query_template"]


def test_operations_rejects_free_form_sql(service):
    ops = Principal(user_id="ops", role=Role.OPERATIONS)
    try:
        service.query_operations(OpsQuery(question="select * from users"), ops)
    except ValueError as exc:
        assert "metric_id" in str(exc)
    else:
        raise AssertionError("free-form SQL should not be accepted")


def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_and_bearer_auth(client, diesel_request):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "roadmind123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    created = client.post(
        "/api/v1/work-orders",
        json=diesel_request.model_dump(mode="json"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 201
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


def test_api_rbac_and_token_redaction(client, diesel_request):
    created = client.post(
        "/api/v1/work-orders",
        json=diesel_request.model_dump(mode="json"),
        headers={"X-Role": "information_officer", "X-User-Id": "info"},
    )
    assert created.status_code == 201
    order_id = created.json()["service_request_id"]
    diagnosed = client.post(
        f"/api/v1/work-orders/{order_id}/diagnose",
        headers={"X-Role": "information_officer", "X-User-Id": "info"},
    )
    assert diagnosed.status_code == 200
    assert all(item["token"] == "***" for item in diagnosed.json()["approvals"])
    denied = client.post(
        f"/api/v1/work-orders/{order_id}/parts/reserve",
        json={"part_codes": []},
        headers={"X-Role": "operations", "X-User-Id": "ops"},
    )
    assert denied.status_code == 403


def test_manual_takeover_resume(service, admin, diesel_request):
    from roadmind.domain.models import WorkOrderStatus

    order = service.create_request(diesel_request, admin)
    # Bypass lifecycle to isolate resume behavior under degraded mode.
    order.status = WorkOrderStatus.MANUAL_TAKEOVER
    order = service.repo.save(order, expected_version=order.version)
    resumed = service.resume_manual_takeover(order.service_request_id, admin)
    assert resumed.status == WorkOrderStatus.REDIAGNOSIS_REQUIRED
    assert resumed.degraded_mode is True


def test_api_maps_rate_limit_to_429_with_retry_after():
    app = create_app()
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    handler = app.exception_handlers[RateLimitExceeded]
    response = asyncio.run(handler(request, RateLimitExceeded("actor-1")))

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert json.loads(response.body)["error"] == "rate_limit_exceeded"


def test_api_maps_open_circuit_to_503():
    app = create_app()
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    handler = app.exception_handlers[CircuitOpen]
    response = asyncio.run(handler(request, CircuitOpen("inventory.reserve")))

    assert response.status_code == 503
    assert json.loads(response.body)["error"] == "upstream_circuit_open"
