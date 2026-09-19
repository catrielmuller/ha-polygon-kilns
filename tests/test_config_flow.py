"""Tests for the Polygon Kilns config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.polygon_kilns.api import (
    PolygonAuthError,
    PolygonConnectionError,
)
from custom_components.polygon_kilns.const import (
    CONF_REFRESH_TOKEN,
    CONF_UID,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("mock_setup_entry")


@pytest.fixture
def mock_setup_entry():
    """Avoid setting up the integration during flow tests."""
    with patch(
        "custom_components.polygon_kilns.async_setup_entry", return_value=True
    ) as mock:
        yield mock


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A valid login creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.polygon_kilns.config_flow.PolygonKilnsClient.async_authenticate"
    ) as mock_auth:
        mock_auth.return_value = AsyncMock(uid="uid123", refresh_token="rt")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@example.com"
    assert result["data"][CONF_UID] == "uid123"
    assert result["data"][CONF_REFRESH_TOKEN] == "rt"


async def test_user_flow_invalid_auth(hass: HomeAssistant) -> None:
    """Bad credentials show invalid_auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.polygon_kilns.config_flow.PolygonKilnsClient.async_authenticate",
        side_effect=PolygonAuthError("INVALID_PASSWORD"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "wrong"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """Network problems show cannot_connect."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.polygon_kilns.config_flow.PolygonKilnsClient.async_authenticate",
        side_effect=PolygonConnectionError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_flow(hass: HomeAssistant, mock_config_entry) -> None:
    """Reauth updates the stored refresh token."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.polygon_kilns.config_flow.PolygonKilnsClient.async_authenticate"
    ) as mock_auth:
        mock_auth.return_value = AsyncMock(uid="uid123", refresh_token="new-rt")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_REFRESH_TOKEN] == "new-rt"


async def test_reauth_flow_wrong_account(hass: HomeAssistant, mock_config_entry) -> None:
    """Reauth with a different account shows an error and leaves the entry intact."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.polygon_kilns.config_flow.PolygonKilnsClient.async_authenticate"
    ) as mock_auth:
        mock_auth.return_value = AsyncMock(uid="other-uid", refresh_token="other-rt")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "other@example.com", CONF_PASSWORD: "secret"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "reauth_account_mismatch"}
    assert mock_config_entry.data[CONF_REFRESH_TOKEN] == "refresh-token"
