from __future__ import annotations

import pytest

from roadmind.domain.auth import PermissionDenied, Principal, require_scope
from roadmind.domain.models import Role, WorkOrderStatus
from roadmind.domain.state_machine import InvalidTransition, transition
from roadmind.infra.repository import OptimisticLockError


def test_create_order_uses_same_id_for_thread_and_hides_pii(service, admin, diesel_request):
    order = service.create_request(diesel_request, admin)
    assert order.thread_id == order.service_request_id
    assert order.reporter_pii_ref.startswith("pii_")
    assert "13900000000" not in order.model_dump_json()
    assert (
        service.vault.reveal(order.reporter_pii_ref, authorized=True)["reporter_phone"]
        == "13900000000"
    )


def test_pii_vault_requires_explicit_authorization(service, admin, diesel_request):
    order = service.create_request(diesel_request, admin)
    with pytest.raises(PermissionError):
        service.vault.reveal(order.reporter_pii_ref, authorized=False)


def test_state_machine_rejects_skipping_diagnosis(service, admin, diesel_request):
    order = service.create_request(diesel_request, admin)
    with pytest.raises(InvalidTransition):
        transition(order, WorkOrderStatus.CLOSED, actor="test", reason="skip")


def test_repository_optimistic_lock(service, admin, diesel_request):
    order = service.create_request(diesel_request, admin)
    with pytest.raises(OptimisticLockError):
        service.repo.save(order, expected_version=999)


def test_repository_increments_version_and_rejects_stale_copy(
    service, admin, diesel_request
):
    order = service.create_request(diesel_request, admin)
    first_writer = service.repo.get(order.service_request_id)
    stale_writer = service.repo.get(order.service_request_id)

    saved = service.repo.save(first_writer, expected_version=first_writer.version)

    assert saved.version == order.version + 1
    with pytest.raises(OptimisticLockError):
        service.repo.save(stale_writer, expected_version=stale_writer.version)


def test_role_scope_denies_unrelated_write():
    principal = Principal(user_id="ops", role=Role.OPERATIONS)
    with pytest.raises(PermissionDenied):
        require_scope(principal, "parts:reserve")
