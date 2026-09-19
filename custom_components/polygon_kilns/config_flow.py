"""Config flow for the Polygon Kilns integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    PolygonAuthError,
    PolygonConnectionError,
    PolygonKilnsApiError,
    PolygonKilnsClient,
)
from .const import (
    CONF_POLL_INTERVAL,
    CONF_REFRESH_TOKEN,
    CONF_UID,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class PolygonKilnsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Polygon Kilns."""

    VERSION = 1

    async def _async_validate(
        self, email: str, password: str
    ) -> tuple[dict[str, str], dict[str, str] | None]:
        """Validate credentials; return (errors, data) tuple."""
        client = get_async_client(self.hass)
        try:
            api = await PolygonKilnsClient.async_authenticate(client, email, password)
        except PolygonAuthError:
            return {"base": "invalid_auth"}, None
        except PolygonConnectionError:
            return {"base": "cannot_connect"}, None
        except PolygonKilnsApiError:
            _LOGGER.exception("Error inesperado durante el login")
            return {"base": "unknown"}, None

        return {}, {
            CONF_UID: api.uid,
            CONF_REFRESH_TOKEN: api.refresh_token,
            "email": email,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, data = await self._async_validate(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if data is not None:
                await self.async_set_unique_id(data[CONF_UID])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_EMAIL], data=data)

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication when the refresh token stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication with email and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, data = await self._async_validate(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if data is not None:
                entry = self._get_reauth_entry()
                if data[CONF_UID] != entry.unique_id:
                    return self.async_show_form(
                        step_id="reauth_confirm",
                        data_schema=USER_SCHEMA,
                        errors={"base": "reauth_account_mismatch"},
                    )
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_REFRESH_TOKEN: data[CONF_REFRESH_TOKEN]},
                )

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the options flow."""
        return PolygonKilnsOptionsFlow()


class PolygonKilnsOptionsFlow(OptionsFlow):
    """Options flow: polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POLL_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_POLL_INTERVAL,
                            max=MAX_POLL_INTERVAL,
                            step=5,
                            mode=NumberSelectorMode.SLIDER,
                            unit_of_measurement="s",
                        )
                    )
                }
            ),
        )
