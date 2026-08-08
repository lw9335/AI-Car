from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from roadmind.application.service import RoadMindService
from roadmind.domain.auth import Principal
from roadmind.domain.models import (
    Brand,
    PowerType,
    Role,
    ServiceMode,
    ServiceRequestCreate,
    VehicleProfile,
)
from roadmind.main import create_app


@pytest.fixture
def service() -> RoadMindService:
    return RoadMindService()


@pytest.fixture
def admin() -> Principal:
    return Principal(user_id="admin-1", role=Role.ADMIN)


@pytest.fixture
def expert() -> Principal:
    return Principal(user_id="expert-1", role=Role.EXPERT)


@pytest.fixture
def diesel_request() -> ServiceRequestCreate:
    return ServiceRequestCreate(
        reporter_name="王队长",
        reporter_phone="13900000000",
        vehicle=VehicleProfile(
            vin="LVBV6PDC8SM000901",
            brand=Brand.FOTON_AUMAN,
            model="银河 9",
            power_type=PowerType.DIESEL,
            model_year=2025,
            configuration_code="AUM-G9-YC6",
        ),
        symptom="重载后故障灯点亮，尿素消耗异常并偶发限扭",
        dtc_codes=["P20EE"],
        telemetry={"upstream_nox_ppm": 410, "downstream_nox_ppm": 355},
        service_mode=ServiceMode.OEM_AUTHORIZED,
        location="佛山顺德",
    )


@pytest.fixture
def ev_request() -> ServiceRequestCreate:
    return ServiceRequestCreate(
        reporter_name="张师傅",
        reporter_phone="13800000000",
        vehicle=VehicleProfile(
            vin="LDPGBCDC0PA000101",
            brand=Brand.DEEPWAY,
            model="深向星辰",
            power_type=PowerType.ELECTRIC,
            model_year=2025,
            configuration_code="DW-HV-600",
        ),
        symptom="雨天后绝缘报警且车辆限制上高压",
        dtc_codes=["P0AA6"],
        telemetry={"insulation_kohm": 82},
        service_mode=ServiceMode.FLEET_SERVICE,
        location="佛山顺德",
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())
