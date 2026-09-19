"""Tests for the Polygon Kilns service handlers."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from custom_components.polygon_kilns.const import (
    DOMAIN,
    SERVICE_CREATE_SCHEDULE,
    SERVICE_DELETE_SCHEDULE,
    SERVICE_START_SCHEDULE,
    SERVICE_STOP_SCHEDULE,
    SERVICE_UPDATE_SCHEDULE,
)


async def _setup(hass: HomeAssistant, mock_config_entry, mock_backend) -> None:
    """Set up the integration against the mocked backend."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


def _start_requests(mock_backend) -> list:
    """Return the recorded calls to the requestStart Cloud Function."""
    return [r for r in mock_backend.requests if "cloudfunctions" in str(r.url)]


async def test_service_start_by_kiln_id_and_num(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """start_schedule with kiln_id + sched_num calls requestStart."""
    await _setup(hass, mock_config_entry, mock_backend)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_START_SCHEDULE,
        {"kiln_id": "K1117", "sched_num": 10},
        blocking=True,
    )

    starts = _start_requests(mock_backend)
    assert len(starts) == 1
    assert json.loads(starts[0].content) == {"kilnId": "K1117", "schedNum": 10}


async def test_service_start_by_device_and_name(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """start_schedule resolves device_id and program name."""
    await _setup(hass, mock_config_entry, mock_backend)

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "K1117")})
    assert device is not None

    await hass.services.async_call(
        DOMAIN,
        SERVICE_START_SCHEDULE,
        {"device_id": device.id, "schedule_name": "GRES CONO 6"},
        blocking=True,
    )

    starts = _start_requests(mock_backend)
    assert len(starts) == 1
    assert json.loads(starts[0].content) == {"kilnId": "K1117", "schedNum": 10}


async def test_service_start_with_future_start_time_schedules(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """start_schedule with start_time arms a scheduled start instead of firing."""
    await _setup(hass, mock_config_entry, mock_backend)
    coordinator = mock_config_entry.runtime_data

    await hass.services.async_call(
        DOMAIN,
        SERVICE_START_SCHEDULE,
        {
            "kiln_id": "K1117",
            "sched_num": 10,
            "start_time": "2030-01-01T07:30:00",
        },
        blocking=True,
    )

    assert _start_requests(mock_backend) == []
    start = coordinator.scheduled_starts["K1117"]
    assert start.sched_num == 10
    assert start.armed is True
    assert start.start_at.tzinfo is not None


async def test_service_stop_schedule(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """stop_schedule patches stopRequested=true on the kiln document."""
    await _setup(hass, mock_config_entry, mock_backend)

    await hass.services.async_call(
        DOMAIN, SERVICE_STOP_SCHEDULE, {"kiln_id": "K1117"}, blocking=True
    )

    patches = [
        r
        for r in mock_backend.requests
        if r.method == "PATCH" and r.url.path.endswith("/kilns/K1117")
    ]
    assert len(patches) == 1
    assert json.loads(patches[0].content)["fields"]["stopRequested"] == {
        "booleanValue": True
    }


async def test_service_create_schedule(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """create_schedule posts a new document to the schedules collection."""
    await _setup(hass, mock_config_entry, mock_backend)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CREATE_SCHEDULE,
        {
            "kiln_id": "K1117",
            "schedule_name": "BIZCOCHO LENTO",
            "sched_num": 11,
            "stages": [
                {"ramp": 100, "temp": 500, "hold": 0},
                {"ramp": 150, "temp": 980, "hold": 15},
            ],
        },
        blocking=True,
    )

    posts = [
        r
        for r in mock_backend.requests
        if r.method == "POST" and r.url.path.endswith("/documents/schedules")
    ]
    assert len(posts) == 1
    fields = json.loads(posts[0].content)["fields"]
    assert fields["name"] == {"stringValue": "BIZCOCHO LENTO"}
    assert fields["schedNum"] == {"integerValue": "11"}
    assert fields["stageCount"] == {"integerValue": "2"}
    assert fields["maxTemp"] == {"doubleValue": 980.0}


async def test_service_update_schedule(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """update_schedule patches only the given fields of the resolved document."""
    await _setup(hass, mock_config_entry, mock_backend)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_UPDATE_SCHEDULE,
        {"kiln_id": "K1117", "sched_num": 10, "name": "GRES CONO 6 LENTO"},
        blocking=True,
    )

    patches = [
        r
        for r in mock_backend.requests
        if r.method == "PATCH" and r.url.path.endswith("/schedules/sched1")
    ]
    assert len(patches) == 1
    assert patches[0].url.params["updateMask.fieldPaths"] == "name"
    assert json.loads(patches[0].content)["fields"]["name"] == {
        "stringValue": "GRES CONO 6 LENTO"
    }


async def test_service_delete_schedule(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """delete_schedule removes the resolved document."""
    await _setup(hass, mock_config_entry, mock_backend)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_DELETE_SCHEDULE,
        {"kiln_id": "K1117", "schedule_name": "GRES CONO 6"},
        blocking=True,
    )

    deletes = [
        r
        for r in mock_backend.requests
        if r.method == "DELETE" and r.url.path.endswith("/schedules/sched1")
    ]
    assert len(deletes) == 1


async def test_service_unknown_kiln_raises(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """A service call for an unknown kiln raises HomeAssistantError."""
    await _setup(hass, mock_config_entry, mock_backend)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_START_SCHEDULE,
            {"kiln_id": "K9999", "sched_num": 1},
            blocking=True,
        )
    assert _start_requests(mock_backend) == []


async def test_service_unknown_device_raises(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """A service call for an unknown device raises HomeAssistantError."""
    await _setup(hass, mock_config_entry, mock_backend)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_STOP_SCHEDULE,
            {"device_id": "nonexistent-device"},
            blocking=True,
        )


async def test_service_unknown_program_name_raises(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """A service call for an unknown program name raises HomeAssistantError."""
    await _setup(hass, mock_config_entry, mock_backend)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_START_SCHEDULE,
            {"kiln_id": "K1117", "schedule_name": "NO EXISTE"},
            blocking=True,
        )


async def test_unload_removes_entity_states(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """Unloading the entry tears down its entities."""
    await _setup(hass, mock_config_entry, mock_backend)
    assert hass.states.get("sensor.gar_kilnn_temperature").state == "117"

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.gar_kilnn_temperature")
    assert state.state == "unavailable"
    assert state.attributes.get("restored") is True


async def test_scheduled_start_offline_kiln_notifies_and_consumes(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """An armed scheduled start with an offline kiln notifies and is consumed."""
    from unittest.mock import AsyncMock, patch

    from custom_components.polygon_kilns.coordinator import PolygonKilnsCoordinator

    await _setup(hass, mock_config_entry, mock_backend)
    coordinator = mock_config_entry.runtime_data

    with (
        patch.object(PolygonKilnsCoordinator, "kiln_is_online", return_value=False),
        patch(
            "homeassistant.components.persistent_notification.async_create"
        ) as mock_notify,
        patch.object(
            coordinator.client, "async_request_start", new=AsyncMock()
        ) as mock_start,
    ):
        await coordinator.async_set_scheduled_start(
            "K1117", 10, dt_util.utcnow() - timedelta(minutes=1), armed=True
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    mock_start.assert_not_called()
    assert "K1117" not in coordinator.scheduled_starts
    mock_notify.assert_called_once()
    assert "K1117" in mock_notify.call_args.kwargs["notification_id"]


async def test_options_flow_changes_poll_interval(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """Changing the poll interval option reloads with the new interval."""
    from homeassistant.data_entry_flow import FlowResultType

    from custom_components.polygon_kilns.const import CONF_POLL_INTERVAL

    await _setup(hass, mock_config_entry, mock_backend)
    assert mock_config_entry.runtime_data.update_interval == timedelta(seconds=30)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert mock_config_entry.options[CONF_POLL_INTERVAL] == 60
    assert mock_config_entry.runtime_data.update_interval == timedelta(seconds=60)


async def test_selected_program_persisted_and_restored(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """The program selection survives a coordinator restart."""
    from custom_components.polygon_kilns.coordinator import PolygonKilnsCoordinator

    await _setup(hass, mock_config_entry, mock_backend)
    coordinator = mock_config_entry.runtime_data

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.gar_kilnn_program_to_start", "option": "GRES CONO 6"},
        blocking=True,
    )
    assert coordinator.selected_programs == {"K1117": 10}

    restored = PolygonKilnsCoordinator(hass, mock_config_entry, coordinator.client)
    await restored.async_setup()
    assert restored.selected_programs == {"K1117": 10}


async def test_new_kiln_entities_added_dynamically(
    hass: HomeAssistant, mock_config_entry, mock_backend
) -> None:
    """A kiln that appears after setup gets entities without a reload."""
    import copy

    from .conftest import KILN_DOC

    await _setup(hass, mock_config_entry, mock_backend)
    assert hass.states.get("sensor.otro_horno_temperature") is None

    new_kiln = copy.deepcopy(KILN_DOC)
    new_kiln["name"] = (
        "projects/polygonkilns/databases/(default)/documents/kilns/K2222"
    )
    new_kiln["fields"]["name"] = {"stringValue": "otro_horno"}
    mock_backend.kilns.append(new_kiln)

    coordinator = mock_config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.otro_horno_temperature") is not None
    assert hass.states.get("binary_sensor.otro_horno_online") is not None
    assert hass.states.get("button.otro_horno_start_program") is not None
    assert hass.states.get("select.otro_horno_program_to_start") is not None
    assert hass.states.get("datetime.otro_horno_scheduled_start") is not None
    assert hass.states.get("switch.otro_horno_scheduled_start_armed") is not None
