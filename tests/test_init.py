"""Tests for the Polygon Kilns integration setup and entities."""

from __future__ import annotations

from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.polygon_kilns.api import (
    PolygonAuthError,
    PolygonConnectionError,
    PolygonKilnsClient,
)
from custom_components.polygon_kilns.const import (
    CONF_POLL_INTERVAL,
    CONF_REFRESH_TOKEN,
    CONF_UID,
    DOMAIN,
    SERVICE_CREATE_SCHEDULE,
    SERVICE_DELETE_SCHEDULE,
    SERVICE_START_SCHEDULE,
    SERVICE_STOP_SCHEDULE,
    SERVICE_UPDATE_SCHEDULE,
)


ALL_SERVICES = (
    SERVICE_START_SCHEDULE,
    SERVICE_STOP_SCHEDULE,
    SERVICE_CREATE_SCHEDULE,
    SERVICE_UPDATE_SCHEDULE,
    SERVICE_DELETE_SCHEDULE,
)


@pytest.fixture
def mock_httpx_client(mock_backend):
    """Route the HA httpx client through the shared mocked Firebase backend."""
    return mock_backend


async def test_setup_and_entities(
    hass: HomeAssistant, mock_config_entry, mock_httpx_client
) -> None:
    """The entry sets up and exposes the kiln entities."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    temp = hass.states.get("sensor.gar_kilnn_temperature")
    assert temp is not None
    assert temp.state == "117"

    state_sensor = hass.states.get("sensor.gar_kilnn_state")
    assert state_sensor is not None
    assert state_sensor.state == "En espera"

    online = hass.states.get("binary_sensor.gar_kilnn_online")
    assert online is not None
    assert online.state == "on"  # lastSeen is far in the future in the fixture

    overheat = hass.states.get("binary_sensor.gar_kilnn_overheat")
    assert overheat is not None
    assert overheat.state == "off"

    program = hass.states.get("select.gar_kilnn_program_to_start")
    assert program is not None
    assert program.attributes["options"] == ["GRES CONO 6"]

    last_firing = hass.states.get("sensor.gar_kilnn_last_firing")
    assert last_firing is not None
    assert last_firing.state == "GRES CONO 6"
    assert last_firing.attributes["energia_kwh"] == 41.61510208


async def test_scheduled_start_fires(
    hass: HomeAssistant, mock_config_entry, mock_httpx_client
) -> None:
    """An armed scheduled start in the past triggers requestStart."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data

    with patch.object(
        coordinator.client, "async_request_start", new=AsyncMock()
    ) as mock_start:
        from datetime import timedelta

        from homeassistant.util import dt as dt_util

        await coordinator.async_set_scheduled_start(
            "K1117", 10, dt_util.utcnow() - timedelta(minutes=1), armed=True
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert mock_start.call_count == 1
    assert "K1117" not in coordinator.scheduled_starts


async def test_setup_revoked_token_starts_reauth(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """A revoked refresh token at setup fails with SETUP_ERROR and starts reauth."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.polygon_kilns.PolygonKilnsClient.async_from_refresh_token",
        side_effect=PolygonAuthError("TOKEN_EXPIRED"),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(
        flow["context"]["source"] == config_entries.SOURCE_REAUTH
        and flow["context"]["entry_id"] == mock_config_entry.entry_id
        for flow in flows
    )


async def test_setup_network_error_retries(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """A network failure at setup marks the entry for retry."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.polygon_kilns.PolygonKilnsClient.async_from_refresh_token",
        side_effect=PolygonConnectionError("down"),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_data_update_does_not_reload(
    hass: HomeAssistant, mock_config_entry, mock_httpx_client
) -> None:
    """A data-only entry update (rotated refresh token) must not reload the entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock()
    ) as mock_reload:
        hass.config_entries.async_update_entry(
            mock_config_entry,
            data={**mock_config_entry.data, CONF_REFRESH_TOKEN: "rotated-token"},
        )
        await hass.async_block_till_done()

    mock_reload.assert_not_called()


async def test_options_update_reloads(
    hass: HomeAssistant, mock_config_entry, mock_httpx_client
) -> None:
    """An options change reloads the entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock()
    ) as mock_reload:
        hass.config_entries.async_update_entry(
            mock_config_entry, options={CONF_POLL_INTERVAL: 60}
        )
        await hass.async_block_till_done()

    mock_reload.assert_called_once_with(mock_config_entry.entry_id)


async def test_refresh_token_rotation_saved_without_reload(
    hass: HomeAssistant, mock_config_entry, mock_httpx_client
) -> None:
    """A rotated refresh token is persisted to the entry without a reload."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data
    with (
        patch.object(
            PolygonKilnsClient,
            "refresh_token",
            new_callable=PropertyMock,
            return_value="rotated-token",
        ),
        patch.object(
            hass.config_entries, "async_reload", new=AsyncMock()
        ) as mock_reload,
    ):
        coordinator._async_maybe_save_refresh_token()
        await hass.async_block_till_done()

    assert mock_config_entry.data[CONF_REFRESH_TOKEN] == "rotated-token"
    mock_reload.assert_not_called()


async def test_unload_removes_services(
    hass: HomeAssistant, mock_config_entry, mock_httpx_client
) -> None:
    """Unloading the last entry unregisters all integration services."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    for service in ALL_SERVICES:
        assert hass.services.has_service(DOMAIN, service)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    for service in ALL_SERVICES:
        assert not hass.services.has_service(DOMAIN, service)


async def test_unload_keeps_services_while_other_entry_loaded(
    hass: HomeAssistant, mock_config_entry, mock_httpx_client
) -> None:
    """Unloading one entry keeps the services while another entry is loaded."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    other_entry = MockConfigEntry(
        domain=DOMAIN,
        title="other@example.com",
        unique_id="uid999",
        data={
            CONF_UID: "uid999",
            CONF_REFRESH_TOKEN: "other-refresh-token",
            "email": "other@example.com",
        },
    )
    mock_config_entry.add_to_hass(hass)
    other_entry.add_to_hass(hass)
    # Setting up the domain loads all its entries (homeassistant.setup).
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert other_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    for service in ALL_SERVICES:
        assert hass.services.has_service(DOMAIN, service)

    assert await hass.config_entries.async_unload(other_entry.entry_id)
    await hass.async_block_till_done()
    for service in ALL_SERVICES:
        assert not hass.services.has_service(DOMAIN, service)


async def test_state_sensor_accepts_backend_states_outside_known_list(
    hass: HomeAssistant, mock_config_entry, mock_httpx_client
) -> None:
    """A real firing reports states (e.g. 'Horneando') beyond the known list;
    the state sensor must still update instead of crashing every refresh."""
    mock_httpx_client.kilns[0]["fields"]["state"] = {"stringValue": "Horneando"}

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state_sensor = hass.states.get("sensor.gar_kilnn_state")
    assert state_sensor is not None
    assert state_sensor.state == "Horneando"
