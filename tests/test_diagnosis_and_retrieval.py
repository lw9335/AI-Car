from __future__ import annotations

from roadmind.domain.models import DiagnosisMode


def test_diesel_diagnosis_routes_to_oem_tool_and_cites_versioned_evidence(
    service, admin, diesel_request
):
    order = service.create_request(diesel_request, admin)
    order = service.run_diagnosis(order.service_request_id, admin)
    assert order.diagnosis.mode == DiagnosisMode.OEM_SPECIAL_TOOL
    assert order.diagnosis.confirmed_code is None
    assert order.diagnosis.requires_expert is True
    assert all(item.brand == order.vehicle.brand for item in order.diagnosis.evidence)
    assert all(item.version for item in order.diagnosis.evidence)
    assert order.status.value == "waiting_expert"


def test_ev_diagnosis_enforces_hv_gate(service, admin, ev_request):
    order = service.create_request(ev_request, admin)
    order = service.run_diagnosis(order.service_request_id, admin)
    assert order.diagnosis.mode == DiagnosisMode.EV_MANUAL_RAG
    assert any("高压" in step for step in order.diagnosis.sop_steps)
    assert any("HV" in conflict or "高压" in conflict for conflict in order.diagnosis.conflicts)


def test_missing_dtc_stays_low_confidence(service, admin, diesel_request):
    diesel_request.dtc_codes = []
    order = service.create_request(diesel_request, admin)
    order = service.run_diagnosis(order.service_request_id, admin)
    assert order.diagnosis.hypotheses[0].code == "SYMPTOM_ONLY"
    assert order.diagnosis.confidence < 0.8
    assert order.diagnosis.candidate_part_codes


def test_tool_call_is_audited_and_parented_under_agent_trace(service, admin, diesel_request):
    order = service.create_request(diesel_request, admin)
    service.run_diagnosis(order.service_request_id, admin)
    audit = service.gateway.audit_log()
    assert {item["tool"] for item in audit} >= {"vehicle.decode_vin", "telemetry.get_live_signals"}
    spans = service.traces.list(order.service_request_id)
    tool_span = next(span for span in spans if span["kind"] == "tool")
    assert tool_span["parent_id"] is not None
