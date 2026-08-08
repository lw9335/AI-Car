from __future__ import annotations

from copy import deepcopy
from threading import RLock

from roadmind.domain.models import PartCandidate, WorkOrder

PARTS = [
    {
        "part_code": "NOX-SENSOR-AU-02",
        "name": "下游 NOx 传感器",
        "brands": {"foton_auman"},
        "models": {"银河 9"},
        "stock": 3,
        "eta_hours": 2,
        "unit_price": 1680.0,
        "is_oem": True,
        "source": "佛山中心仓",
    },
    {
        "part_code": "NOX-SENSOR-AF-02",
        "name": "兼容下游 NOx 传感器",
        "brands": {"foton_auman"},
        "models": {"银河 9"},
        "stock": 8,
        "eta_hours": 3,
        "unit_price": 920.0,
        "is_oem": False,
        "source": "合作供应商",
    },
    {
        "part_code": "UREA-NOZZLE-AU-01",
        "name": "尿素喷嘴",
        "brands": {"foton_auman"},
        "models": {"银河 9"},
        "stock": 5,
        "eta_hours": 2,
        "unit_price": 560.0,
        "is_oem": True,
        "source": "顺德区域仓",
    },
    {
        "part_code": "FUEL-FILTER-BC-01",
        "name": "燃油精滤器",
        "brands": {"baic_truck"},
        "models": {"追梦"},
        "stock": 4,
        "eta_hours": 4,
        "unit_price": 380.0,
        "is_oem": True,
        "source": "佛山中心仓",
    },
    {
        "part_code": "HVIL-HARNESS-DW-01",
        "name": "高压互锁线束",
        "brands": {"deepway"},
        "models": {"深向星辰"},
        "stock": 2,
        "eta_hours": 6,
        "unit_price": 2350.0,
        "is_oem": True,
        "source": "广州新能源仓",
    },
    {
        "part_code": "HV-CONNECTOR-DW-03",
        "name": "高压防水连接器",
        "brands": {"deepway"},
        "models": {"深向星辰"},
        "stock": 3,
        "eta_hours": 6,
        "unit_price": 1280.0,
        "is_oem": True,
        "source": "广州新能源仓",
    },
]


class PartsAgent:
    """DTC-gated part recommendation, VIN compatibility and reservation lifecycle."""

    def __init__(self) -> None:
        self._stock = {item["part_code"]: item["stock"] for item in PARTS}
        self._reservations: dict[str, list[str]] = {}
        self._lock = RLock()

    def candidates(self, order: WorkOrder) -> list[PartCandidate]:
        if not order.diagnosis or not order.diagnosis.confirmed_code:
            raise ValueError("parts recommendation requires an expert-confirmed diagnosis")
        evidence_map = {
            part: [evidence.evidence_id]
            for evidence in order.diagnosis.evidence
            for part in order.diagnosis.candidate_part_codes
        }
        requested = set(order.diagnosis.candidate_part_codes)
        results = []
        for item in PARTS:
            compatible = (
                order.vehicle.brand.value in item["brands"]
                and order.vehicle.model in item["models"]
            )
            if not compatible:
                continue
            base_code = item["part_code"].replace("AF", "AU")
            if item["part_code"] not in requested and base_code not in requested:
                continue
            results.append(
                PartCandidate(
                    part_code=item["part_code"],
                    name=item["name"],
                    compatibility=f"{order.vehicle.vin} / {order.vehicle.configuration_code}",
                    source=item["source"],
                    stock=self._stock[item["part_code"]],
                    eta_hours=item["eta_hours"],
                    unit_price=item["unit_price"],
                    is_oem=item["is_oem"],
                    evidence_refs=evidence_map.get(item["part_code"], []),
                )
            )
        return sorted(results, key=lambda part: (part.stock <= 0, part.eta_hours, not part.is_oem))

    def reserve(self, order_id: str, part_codes: list[str]) -> None:
        if len(part_codes) != len(set(part_codes)):
            raise ValueError("duplicate part code in reservation")
        with self._lock:
            for code in part_codes:
                if self._stock.get(code, 0) <= 0:
                    raise ValueError(f"part out of stock: {code}")
            for code in part_codes:
                self._stock[code] -= 1
            self._reservations[order_id] = list(part_codes)

    def release(self, order_id: str) -> list[str]:
        with self._lock:
            codes = self._reservations.pop(order_id, [])
            for code in codes:
                self._stock[code] += 1
            return codes

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return deepcopy(self._stock)
