from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

from ortools.sat.python import cp_model

from roadmind.domain.models import DispatchCandidate, ServiceMode, WorkOrder


@dataclass(frozen=True)
class Resource:
    resource_id: str
    display_name: str
    resource_type: str
    skills: frozenset[str]
    brands: frozenset[str]
    service_modes: frozenset[str]
    distance_km: float
    workload: int
    available: bool = True


RESOURCES = [
    Resource(
        "eng_001",
        "陈工（发动机/后处理）",
        "engineer",
        frozenset({"P20EE", "P0087", "diesel"}),
        frozenset({"foton_auman", "baic_truck"}),
        frozenset(mode.value for mode in ServiceMode),
        8.2,
        1,
    ),
    Resource(
        "eng_002",
        "李工（新能源高压）",
        "engineer",
        frozenset({"P0AA6", "U1110", "electric", "hv_certified"}),
        frozenset({"deepway"}),
        frozenset({ServiceMode.OEM_AUTHORIZED, ServiceMode.FLEET_SERVICE}),
        21.4,
        0,
    ),
    Resource(
        "shop_001",
        "顺德授权服务站 1 号工位",
        "workbay",
        frozenset({"diesel", "electric", "lift_18t"}),
        frozenset({"foton_auman", "baic_truck", "deepway"}),
        frozenset({ServiceMode.OEM_AUTHORIZED, ServiceMode.FLEET_SERVICE}),
        5.6,
        2,
    ),
    Resource(
        "partner_001",
        "华南合作修理厂技术组",
        "partner_shop",
        frozenset({"diesel", "roadside"}),
        frozenset({"foton_auman", "baic_truck"}),
        frozenset({ServiceMode.PARTNER_REPAIR, ServiceMode.RETAIL_RETURNING}),
        14.8,
        1,
    ),
]


class LeaseConflict(RuntimeError):
    pass


class ResourceLeaseBook:
    """Redis-lease semantics implemented locally for deterministic tests."""

    def __init__(self) -> None:
        self._leases: dict[str, tuple[str, datetime]] = {}
        self._lock = RLock()

    def reserve(self, resource_id: str, order_id: str, *, ttl_seconds: int = 120) -> None:
        now = datetime.now(UTC)
        with self._lock:
            current = self._leases.get(resource_id)
            if current and current[1] > now and current[0] != order_id:
                raise LeaseConflict(resource_id)
            self._leases[resource_id] = (order_id, now + timedelta(seconds=ttl_seconds))

    def release(self, resource_id: str, order_id: str) -> None:
        with self._lock:
            current = self._leases.get(resource_id)
            if current and current[0] == order_id:
                self._leases.pop(resource_id, None)


class DispatchAgent:
    """Hard-filter then jointly rank skill, ETA, workload and mode compatibility."""

    def __init__(self, lease_book: ResourceLeaseBook | None = None) -> None:
        self.lease_book = lease_book or ResourceLeaseBook()

    def candidates(self, order: WorkOrder) -> list[DispatchCandidate]:
        diagnosis_code = (
            order.diagnosis.confirmed_code
            if order.diagnosis and order.diagnosis.confirmed_code
            else (order.dtc_codes[0] if order.dtc_codes else "")
        )
        power_skill = order.vehicle.power_type.value
        candidates = []
        for resource in RESOURCES:
            reasons = []
            if not resource.available:
                continue
            if order.vehicle.brand.value not in resource.brands:
                continue
            if order.service_mode.value not in resource.service_modes:
                continue
            if power_skill not in resource.skills:
                continue
            if (
                order.vehicle.power_type.value == "electric"
                and "hv_certified" not in resource.skills
            ):
                continue
            skill_match = 1.0 if diagnosis_code in resource.skills else 0.68
            eta = max(10, round(resource.distance_km / 0.55 + 12))
            score = 100 * (
                0.42 * skill_match
                + 0.20 * max(0.0, 1 - eta / 180)
                + 0.18 * max(0.0, 1 - resource.workload / 5)
                + 0.20
            )
            reasons.extend(
                [
                    f"品牌匹配={order.vehicle.brand.value}",
                    f"服务模式匹配={order.service_mode.value}",
                    f"技能匹配={diagnosis_code or power_skill}",
                    "已通过排班、区域与资质硬约束",
                ]
            )
            candidates.append(
                DispatchCandidate(
                    resource_id=resource.resource_id,
                    display_name=resource.display_name,
                    resource_type=resource.resource_type,
                    skills=sorted(resource.skills),
                    distance_km=resource.distance_km,
                    eta_minutes=eta,
                    workload=resource.workload,
                    score=round(score, 2),
                    constraint_reasons=reasons,
                )
            )
        if not candidates:
            return []
        optimal_resource_id = self._solve_cp_sat(candidates)
        return sorted(
            candidates,
            key=lambda item: (item.resource_id == optimal_resource_id, item.score),
            reverse=True,
        )

    @staticmethod
    def _solve_cp_sat(candidates: list[DispatchCandidate]) -> str:
        """Select the globally best feasible candidate with an auditable integer objective."""
        model = cp_model.CpModel()
        selected = {
            candidate.resource_id: model.new_bool_var(f"select_{candidate.resource_id}")
            for candidate in candidates
        }
        model.add(sum(selected.values()) == 1)
        model.maximize(
            sum(
                round(candidate.score * 100) * selected[candidate.resource_id]
                for candidate in candidates
            )
        )
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 0.5
        status = solver.solve(model)
        if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            raise RuntimeError("CP-SAT did not find a feasible dispatch assignment")
        return next(
            resource_id for resource_id, variable in selected.items() if solver.value(variable) == 1
        )

    def reserve(self, order: WorkOrder, resource_id: str) -> None:
        if resource_id not in {item.resource_id for item in order.dispatch_candidates}:
            raise ValueError("resource was not in the validated candidate set")
        self.lease_book.reserve(resource_id, order.service_request_id)

    def verify_assignment(self, order: WorkOrder, resource_id: str) -> None:
        candidate = next(
            (item for item in order.dispatch_candidates if item.resource_id == resource_id), None
        )
        if candidate is None:
            raise ValueError("assignment failed independent constraint verification")
        if order.vehicle.power_type.value == "electric" and "hv_certified" not in candidate.skills:
            raise ValueError("electric work order requires hv_certified resource")
