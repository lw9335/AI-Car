from __future__ import annotations

from roadmind.domain.auth import Principal
from roadmind.domain.models import (
    ClosureApproval,
    ClosureRequest,
    DiagnosisMismatch,
    DispatchApproval,
    ExpertDecision,
    PartsReservationRequest,
    Role,
    WorkOrderStatus,
)


def confirm_and_prepare(service, admin, expert, request):
    order = service.create_request(request, admin)
    order = service.run_diagnosis(order.service_request_id, admin)
    order = service.confirm_diagnosis(
        order.service_request_id,
        ExpertDecision(
            diagnosis_id=order.diagnosis.diagnosis_id,
            approved=True,
            confirmed_code=order.diagnosis.hypotheses[0].code,
            comment="专检与证据一致",
        ),
        expert,
    )
    return order


def test_parallel_fulfillment_and_join_to_ready(service, admin, expert, diesel_request):
    order = confirm_and_prepare(service, admin, expert, diesel_request)
    assert order.status == WorkOrderStatus.FULFILLING
    assert order.dispatch_candidates
    assert order.parts_candidates
    assert order.dispatch_candidates[0].score == max(
        candidate.score for candidate in order.dispatch_candidates
    )
    assert any(event.event_type == "fulfillment.candidates_ready" for event in order.timeline)

    dispatcher = Principal(user_id="dispatcher", role=Role.DISPATCHER)
    approval = next(item for item in order.approvals if item.action == "dispatch.assign")
    order = service.approve_dispatch(
        order.service_request_id,
        DispatchApproval(
            resource_id=order.dispatch_candidates[0].resource_id,
            approval_token=approval.token,
        ),
        dispatcher,
    )
    assert order.status == WorkOrderStatus.FULFILLING

    parts_manager = Principal(user_id="parts", role=Role.PARTS_MANAGER)
    order = service.reserve_parts(
        order.service_request_id,
        PartsReservationRequest(part_codes=[order.parts_candidates[0].part_code], bring_both=True),
        parts_manager,
    )
    assert order.status == WorkOrderStatus.READY_FOR_SERVICE
    assert order.selected_resource_id
    assert order.reserved_part_codes


def test_dispatch_requires_valid_approval_token(service, admin, expert, diesel_request):
    order = confirm_and_prepare(service, admin, expert, diesel_request)
    dispatcher = Principal(user_id="dispatcher", role=Role.DISPATCHER)
    try:
        service.approve_dispatch(
            order.service_request_id,
            DispatchApproval(
                resource_id=order.dispatch_candidates[0].resource_id,
                approval_token="stale",
            ),
            dispatcher,
        )
    except ValueError as exc:
        assert "approval token" in str(exc)
    else:
        raise AssertionError("stale token was accepted")


def test_parts_reservation_retry_is_idempotent(service, admin, expert, diesel_request):
    order = confirm_and_prepare(service, admin, expert, diesel_request)
    parts_manager = Principal(user_id="parts", role=Role.PARTS_MANAGER)
    code = order.parts_candidates[0].part_code
    before = service.parts.snapshot()[code]

    first = service.reserve_parts(
        order.service_request_id,
        PartsReservationRequest(part_codes=[code]),
        parts_manager,
    )
    retried = service.reserve_parts(
        order.service_request_id,
        PartsReservationRequest(part_codes=[code]),
        parts_manager,
    )

    assert service.parts.snapshot()[code] == before - 1
    assert retried.version == first.version


def test_ev_dispatch_candidates_all_have_hv_cert(service, admin, expert, ev_request):
    order = confirm_and_prepare(service, admin, expert, ev_request)
    assert order.dispatch_candidates
    assert all("hv_certified" in candidate.skills for candidate in order.dispatch_candidates)


def test_mismatch_freezes_plan_and_compensates(service, admin, expert, diesel_request):
    order = confirm_and_prepare(service, admin, expert, diesel_request)
    dispatcher = Principal(user_id="dispatcher", role=Role.DISPATCHER)
    parts_manager = Principal(user_id="parts", role=Role.PARTS_MANAGER)
    approval = next(item for item in order.approvals if item.action == "dispatch.assign")
    order = service.approve_dispatch(
        order.service_request_id,
        DispatchApproval(
            resource_id=order.dispatch_candidates[0].resource_id, approval_token=approval.token
        ),
        dispatcher,
    )
    code = order.parts_candidates[0].part_code
    before = service.parts.snapshot()[code]
    order = service.reserve_parts(
        order.service_request_id,
        PartsReservationRequest(part_codes=[code]),
        parts_manager,
    )
    assert service.parts.snapshot()[code] == before - 1
    old_plan = order.task_plan.plan_version
    order = service.report_mismatch(
        order.service_request_id,
        DiagnosisMismatch(actual_code="P204F", evidence="现场喷射量测试不一致"),
        admin,
    )
    assert order.status == WorkOrderStatus.REDIAGNOSIS_REQUIRED
    assert order.task_plan.plan_version == old_plan + 1
    assert old_plan in order.task_plan.frozen_versions
    assert not order.reserved_part_codes
    assert service.parts.snapshot()[code] == before
    assert any(event.event_type == "saga.compensated" for event in order.timeline)
    compensated_tools = {item["tool"] for item in service.gateway.audit_log()}
    assert {"workflow.release_resource", "inventory.release"} <= compensated_tools


def test_normal_closure_creates_quarantined_case_and_outbox(service, admin, expert, diesel_request):
    order = confirm_and_prepare(service, admin, expert, diesel_request)
    dispatcher = Principal(user_id="dispatcher", role=Role.DISPATCHER)
    parts_manager = Principal(user_id="parts", role=Role.PARTS_MANAGER)
    tech = Principal(user_id="tech", role=Role.TECHNICIAN)
    approval = next(item for item in order.approvals if item.action == "dispatch.assign")
    order = service.approve_dispatch(
        order.service_request_id,
        DispatchApproval(
            resource_id=order.dispatch_candidates[0].resource_id, approval_token=approval.token
        ),
        dispatcher,
    )
    order = service.reserve_parts(
        order.service_request_id,
        PartsReservationRequest(part_codes=[order.parts_candidates[0].part_code]),
        parts_manager,
    )
    order = service.start_service(order.service_request_id, tech)
    order = service.close_order(
        order.service_request_id,
        ClosureRequest(
            resolution="完成更换、自适应学习和路试验证",
            actual_part_codes=order.reserved_part_codes,
            customer_rating=5,
        ),
        tech,
    )
    assert order.status == WorkOrderStatus.WAITING_CLOSE_APPROVAL
    approval = next(item for item in order.approvals if item.action == "service.close")
    order = service.approve_closure(
        order.service_request_id,
        ClosureApproval(
            approval_token=approval.token,
            approved=True,
            comment="结案证据与质量门禁通过",
        ),
        expert,
    )
    assert order.status == WorkOrderStatus.CLOSED
    case_event = next(
        e for e in order.timeline if e.event_type == "knowledge.case_candidate_created"
    )
    assert case_event.data["publication_status"] == "quarantine_pending_quality_review"
    assert any(message.topic == "workorder.closed" for message in service.outbox.pending())


def test_rejected_closure_returns_to_service(service, admin, expert, diesel_request):
    order = confirm_and_prepare(service, admin, expert, diesel_request)
    dispatcher = Principal(user_id="dispatcher", role=Role.DISPATCHER)
    parts_manager = Principal(user_id="parts", role=Role.PARTS_MANAGER)
    tech = Principal(user_id="tech", role=Role.TECHNICIAN)
    dispatch_approval = next(item for item in order.approvals if item.action == "dispatch.assign")
    order = service.approve_dispatch(
        order.service_request_id,
        DispatchApproval(
            resource_id=order.dispatch_candidates[0].resource_id,
            approval_token=dispatch_approval.token,
        ),
        dispatcher,
    )
    order = service.reserve_parts(
        order.service_request_id,
        PartsReservationRequest(part_codes=[order.parts_candidates[0].part_code]),
        parts_manager,
    )
    order = service.start_service(order.service_request_id, tech)
    order = service.close_order(
        order.service_request_id,
        ClosureRequest(
            resolution="完成维修但路试证据不足",
            actual_part_codes=order.reserved_part_codes,
            customer_rating=4,
        ),
        tech,
    )
    closure_approval = next(item for item in order.approvals if item.action == "service.close")

    order = service.approve_closure(
        order.service_request_id,
        ClosureApproval(
            approval_token=closure_approval.token,
            approved=False,
            comment="需要补充负载路试记录",
        ),
        expert,
    )

    assert order.status == WorkOrderStatus.IN_SERVICE
    assert closure_approval.approval_id == order.approvals[-1].approval_id
    assert order.approvals[-1].status == "rejected"


def test_native_langgraph_interrupt_resume(service):
    first = service.native_approval.start("sr-native", {"action": "dispatch.assign"})
    assert "__interrupt__" in first
    resumed = service.native_approval.resume("sr-native", {"approved": True, "by": "dispatcher"})
    assert resumed["approved"] is True
