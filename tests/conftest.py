"""Common fixtures for the Polygon Kilns tests."""

from __future__ import annotations

import copy
import json
from unittest.mock import patch

import httpx
import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.polygon_kilns.const import (
    CONF_REFRESH_TOKEN,
    CONF_UID,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a configured entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="uid123",
        data={
            CONF_UID: "uid123",
            CONF_REFRESH_TOKEN: "refresh-token",
            "email": "user@example.com",
        },
    )


KILN_DOC = {
    "name": "projects/polygonkilns/databases/(default)/documents/kilns/K1117",
    "fields": {
        "name": {"stringValue": "gar_Kilnn"},
        "ownerId": {"stringValue": "owner-uid"},
        "state": {"stringValue": "En espera"},
        "command": {"stringValue": "start"},
        "fwVersion": {"stringValue": "2.76"},
        "currentSchedule": {"integerValue": "10"},
        "scheduleName": {"stringValue": "GRES CONO 6"},
        "currentStage": {"integerValue": "5"},
        "totalStages": {"integerValue": "4"},
        "segmentPhase": {"stringValue": "ramp"},
        "progress": {"doubleValue": 1},
        "temperature": {"integerValue": "117"},
        "setpoint": {"doubleValue": 802.9},
        "etaSeconds": {"integerValue": "0"},
        "elapsedSeconds": {"integerValue": "38002"},
        "energyKWh": {"doubleValue": 41.61510208},
        "cost": {"doubleValue": 17478.3428736},
        "rssi": {"integerValue": "-54"},
        "lastSeen": {"timestampValue": "2999-06-10T14:08:37.500Z"},
        "stopRequested": {"booleanValue": False},
        "sensorFault": {"booleanValue": False},
        "overheatFault": {"booleanValue": False},
        "thermocoupleError": {"booleanValue": False},
    },
}

SCHEDULE_DOC = {
    "name": "projects/polygonkilns/databases/(default)/documents/schedules/sched1",
    "fields": {
        "kilnId": {"stringValue": "K1117"},
        "schedNum": {"integerValue": "10"},
        "name": {"stringValue": "GRES CONO 6"},
        "stageCount": {"integerValue": "4"},
        "maxTemp": {"integerValue": "1200"},
        "version": {"integerValue": "1"},
        "createdBy": {"stringValue": "device"},
        "stages": {
            "arrayValue": {
                "values": [
                    {
                        "mapValue": {
                            "fields": {
                                "ramp": {"integerValue": "120"},
                                "temp": {"integerValue": "600"},
                                "hold": {"integerValue": "0"},
                            }
                        }
                    }
                ]
            }
        },
    },
}

FIRING_DOC = {
    "name": "projects/polygonkilns/databases/(default)/documents/kilns/K1117/firings/f1",
    "fields": {
        "schedule": {"stringValue": "GRES CONO 6"},
        "state": {"stringValue": "finished"},
        "energyKWh": {"doubleValue": 41.61510208},
        "cost": {"doubleValue": 17478.3428736},
        "startTime": {"timestampValue": "2026-06-09T20:03:01.949Z"},
        "endTime": {"timestampValue": "2026-06-10T06:37:22.914Z"},
    },
}


class MockFirebaseBackend:
    """In-memory Firebase backend routing the HA httpx client."""

    def __init__(self) -> None:
        """Initialize with the default fixture documents."""
        self.kilns = [copy.deepcopy(KILN_DOC)]
        self.schedules = [copy.deepcopy(SCHEDULE_DOC)]
        self.firings = [copy.deepcopy(FIRING_DOC)]
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Handle an HTTP request against the mocked backend."""
        self.requests.append(request)
        url = str(request.url)
        if "securetoken" in url:
            return httpx.Response(
                200,
                json={
                    "user_id": "uid123",
                    "id_token": "id-token",
                    "refresh_token": "refresh-token",
                    "expires_in": "3600",
                },
            )
        if "cloudfunctions" in url:
            return httpx.Response(200, json={"ok": True})
        if url.endswith(":runQuery"):
            return self._run_query(request)
        if request.method == "POST" and url.endswith("/documents/schedules"):
            return httpx.Response(
                200,
                json={
                    "name": "projects/polygonkilns/databases/(default)/documents"
                    "/schedules/new1",
                    "fields": {},
                },
            )
        if request.method == "PATCH":
            return httpx.Response(
                200,
                json={
                    "name": "projects/polygonkilns/databases/(default)/documents"
                    + request.url.path.split("/documents", 1)[-1],
                    "fields": {},
                },
            )
        if request.method == "DELETE":
            return httpx.Response(200)
        return httpx.Response(404)

    def _run_query(self, request: httpx.Request) -> httpx.Response:
        """Serve a Firestore structured query from the in-memory documents."""
        query = json.loads(request.content)["structuredQuery"]
        collection = query["from"][0]["collectionId"]
        if collection == "kilns":
            # Owned query returns nothing; shared query returns the kilns.
            if "fieldFilter" in query.get("where", {}):
                return httpx.Response(200, json=[])
            return httpx.Response(
                200, json=[{"document": kiln} for kiln in self.kilns]
            )
        if collection == "schedules":
            return httpx.Response(
                200, json=[{"document": doc} for doc in self.schedules]
            )
        if collection == "firings":
            return httpx.Response(
                200, json=[{"document": doc} for doc in self.firings]
            )
        return httpx.Response(200, json=[])


@pytest.fixture
def mock_backend():
    """Route the HA httpx client through a mocked Firebase backend."""
    backend = MockFirebaseBackend()
    client = httpx.AsyncClient(transport=httpx.MockTransport(backend.handler))
    with patch("custom_components.polygon_kilns.get_async_client", return_value=client):
        yield backend
