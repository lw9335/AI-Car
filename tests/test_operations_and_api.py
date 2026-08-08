from __future__ import annotations

from roadmind.domain.auth import Principal
from roadmind.domain.models import OpsQuery, Role


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


def test_health_and_static_console(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    page = client.get("/")
    assert page.status_code == 200
    assert "RoadMind" in page.text


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
