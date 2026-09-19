"""The Polygon Kilns integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.util import dt as dt_util

from .api import (
    PolygonAuthError,
    PolygonConnectionError,
    PolygonKilnsApiError,
    PolygonKilnsClient,
)
from .const import (
    ATTR_KILN_ID,
    ATTR_SCHED_NUM,
    ATTR_SCHEDULE_NAME,
    ATTR_STAGES,
    ATTR_START_TIME,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    SERVICE_CREATE_SCHEDULE,
    SERVICE_DELETE_SCHEDULE,
    SERVICE_START_SCHEDULE,
    SERVICE_STOP_SCHEDULE,
    SERVICE_UPDATE_SCHEDULE,
)
from .coordinator import PolygonConfigEntry, PolygonKilnsCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DATETIME,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

STAGE_SCHEMA = vol.Schema(
    {
        vol.Required("ramp"): vol.Coerce(float),
        vol.Required("temp"): vol.Coerce(float),
        vol.Required("hold"): vol.Coerce(int),
    }
)

SCHEDULE_TARGET_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_KILN_ID): cv.string, vol.Optional("device_id"): cv.string}
)


async def async_setup_entry(hass: HomeAssistant, entry: PolygonConfigEntry) -> bool:
    """Set up Polygon Kilns from a config entry."""
    try:
        client = await PolygonKilnsClient.async_from_refresh_token(
            get_async_client(hass), entry.data[CONF_REFRESH_TOKEN]
        )
    except PolygonAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except PolygonConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = PolygonKilnsCoordinator(hass, entry, client)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    options_snapshot = dict(entry.options)

    async def _async_update_listener(
        hass: HomeAssistant, entry: PolygonConfigEntry
    ) -> None:
        """Reload the entry only when options change (not on token rotation)."""
        if dict(entry.options) != options_snapshot:
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PolygonConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    other_entries = [
        other
        for other in hass.config_entries.async_loaded_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ]
    if not other_entries:
        for service in (
            SERVICE_START_SCHEDULE,
            SERVICE_STOP_SCHEDULE,
            SERVICE_CREATE_SCHEDULE,
            SERVICE_UPDATE_SCHEDULE,
            SERVICE_DELETE_SCHEDULE,
        ):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)
    return True


def _get_coordinators(hass: HomeAssistant) -> list[PolygonKilnsCoordinator]:
    """Return all loaded coordinators."""
    return [
        entry.runtime_data for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    ]


def _resolve_kiln_id(hass: HomeAssistant, call: ServiceCall) -> str:
    """Resolve the target kiln id from a service call."""
    if kiln_id := call.data.get(ATTR_KILN_ID):
        return kiln_id
    device_id = call.data["device_id"]
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise HomeAssistantError(f"Dispositivo desconocido: {device_id}")
    for domain, identifier in device.identifiers:
        if domain == DOMAIN:
            return identifier
    raise HomeAssistantError(f"El dispositivo {device_id} no es un horno Polygon")


def _find_coordinator(hass: HomeAssistant, kiln_id: str) -> PolygonKilnsCoordinator:
    """Find the coordinator that can see the given kiln."""
    for coordinator in _get_coordinators(hass):
        if coordinator.data and kiln_id in coordinator.data.kilns:
            return coordinator
    raise HomeAssistantError(f"Ningún horno con id '{kiln_id}' está disponible")


def _resolve_sched_num(
    coordinator: PolygonKilnsCoordinator, kiln_id: str, call: ServiceCall
) -> int:
    """Resolve the program number from a service call."""
    if sched_num := call.data.get(ATTR_SCHED_NUM):
        return int(sched_num)
    name = call.data[ATTR_SCHEDULE_NAME]
    for schedule in coordinator.data.schedules.get(kiln_id, []):
        if schedule.get("name") == name:
            return int(schedule["schedNum"])
    raise HomeAssistantError(f"El programa '{name}' no existe en el horno '{kiln_id}'")


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services (once)."""
    if hass.services.has_service(DOMAIN, SERVICE_START_SCHEDULE):
        return

    async def handle_start(call: ServiceCall) -> None:
        kiln_id = _resolve_kiln_id(hass, call)
        coordinator = _find_coordinator(hass, kiln_id)
        sched_num = _resolve_sched_num(coordinator, kiln_id, call)
        if start_time := call.data.get(ATTR_START_TIME):
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=dt_util.get_default_time_zone())
            await coordinator.async_set_scheduled_start(
                kiln_id, sched_num, start_time, armed=True
            )
            return
        try:
            await coordinator.client.async_request_start(kiln_id, sched_num)
        except PolygonKilnsApiError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    async def handle_stop(call: ServiceCall) -> None:
        kiln_id = _resolve_kiln_id(hass, call)
        coordinator = _find_coordinator(hass, kiln_id)
        try:
            await coordinator.client.async_stop_kiln(kiln_id)
        except PolygonKilnsApiError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    async def handle_create(call: ServiceCall) -> None:
        kiln_id = _resolve_kiln_id(hass, call)
        coordinator = _find_coordinator(hass, kiln_id)
        try:
            await coordinator.client.async_create_schedule(
                kiln_id=kiln_id,
                name=call.data[ATTR_SCHEDULE_NAME],
                sched_num=call.data[ATTR_SCHED_NUM],
                stages=[dict(stage) for stage in call.data[ATTR_STAGES]],
            )
        except PolygonKilnsApiError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    async def handle_update(call: ServiceCall) -> None:
        kiln_id = _resolve_kiln_id(hass, call)
        coordinator = _find_coordinator(hass, kiln_id)
        sched_num = _resolve_sched_num(coordinator, kiln_id, call)
        schedule = next(
            (
                s
                for s in coordinator.data.schedules.get(kiln_id, [])
                if s.get("schedNum") == sched_num
            ),
            None,
        )
        if schedule is None:
            raise HomeAssistantError(
                f"El programa {sched_num} no existe en el horno '{kiln_id}'"
            )
        fields: dict = {}
        if name := call.data.get("name"):
            fields["name"] = name
        if stages := call.data.get(ATTR_STAGES):
            fields["stages"] = [dict(stage) for stage in stages]
            fields["stageCount"] = len(stages)
            fields["maxTemp"] = max(s["temp"] for s in stages)
        if not fields:
            raise HomeAssistantError("No se indicaron campos a actualizar")
        try:
            await coordinator.client.async_update_schedule(schedule["_id"], fields)
        except PolygonKilnsApiError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    async def handle_delete(call: ServiceCall) -> None:
        kiln_id = _resolve_kiln_id(hass, call)
        coordinator = _find_coordinator(hass, kiln_id)
        sched_num = _resolve_sched_num(coordinator, kiln_id, call)
        schedule = next(
            (
                s
                for s in coordinator.data.schedules.get(kiln_id, [])
                if s.get("schedNum") == sched_num
            ),
            None,
        )
        if schedule is None:
            raise HomeAssistantError(
                f"El programa {sched_num} no existe en el horno '{kiln_id}'"
            )
        try:
            await coordinator.client.async_delete_schedule(schedule["_id"])
        except PolygonKilnsApiError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    start_stop_schema = vol.All(
        SCHEDULE_TARGET_SCHEMA.extend(
            {
                vol.Exclusive(ATTR_SCHED_NUM, "schedule"): vol.Coerce(int),
                vol.Exclusive(ATTR_SCHEDULE_NAME, "schedule"): cv.string,
            }
        ),
        cv.has_at_least_one_key(ATTR_KILN_ID, "device_id"),
        cv.has_at_least_one_key(ATTR_SCHED_NUM, ATTR_SCHEDULE_NAME),
    )

    start_schema = vol.All(
        SCHEDULE_TARGET_SCHEMA.extend(
            {
                vol.Exclusive(ATTR_SCHED_NUM, "schedule"): vol.Coerce(int),
                vol.Exclusive(ATTR_SCHEDULE_NAME, "schedule"): cv.string,
                vol.Optional(ATTR_START_TIME): cv.datetime,
            }
        ),
        cv.has_at_least_one_key(ATTR_KILN_ID, "device_id"),
        cv.has_at_least_one_key(ATTR_SCHED_NUM, ATTR_SCHEDULE_NAME),
    )

    hass.services.async_register(
        DOMAIN, SERVICE_START_SCHEDULE, handle_start, schema=start_schema
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_SCHEDULE,
        handle_stop,
        schema=vol.All(
            SCHEDULE_TARGET_SCHEMA, cv.has_at_least_one_key(ATTR_KILN_ID, "device_id")
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_SCHEDULE,
        handle_create,
        schema=vol.All(
            SCHEDULE_TARGET_SCHEMA.extend(
                {
                    vol.Required(ATTR_SCHEDULE_NAME): cv.string,
                    vol.Required(ATTR_SCHED_NUM): vol.Coerce(int),
                    vol.Required(ATTR_STAGES): [STAGE_SCHEMA],
                }
            ),
            cv.has_at_least_one_key(ATTR_KILN_ID, "device_id"),
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_SCHEDULE,
        handle_update,
        schema=vol.All(
            SCHEDULE_TARGET_SCHEMA.extend(
                {
                    vol.Exclusive(ATTR_SCHED_NUM, "schedule"): vol.Coerce(int),
                    vol.Exclusive(ATTR_SCHEDULE_NAME, "schedule"): cv.string,
                    vol.Optional("name"): cv.string,
                    vol.Optional(ATTR_STAGES): [STAGE_SCHEMA],
                }
            ),
            cv.has_at_least_one_key(ATTR_KILN_ID, "device_id"),
            cv.has_at_least_one_key(ATTR_SCHED_NUM, ATTR_SCHEDULE_NAME),
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_SCHEDULE,
        handle_delete,
        schema=start_stop_schema,
    )
