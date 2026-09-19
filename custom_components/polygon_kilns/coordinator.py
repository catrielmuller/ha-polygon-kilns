"""Data update coordinator for the Polygon Kilns integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    PolygonAuthError,
    PolygonConnectionError,
    PolygonKilnsApiError,
    PolygonKilnsClient,
)
from .const import (
    CONF_POLL_INTERVAL,
    CONF_REFRESH_TOKEN,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    OFFLINE_AFTER,
    STARTABLE_STATES,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

type PolygonConfigEntry = ConfigEntry[PolygonKilnsCoordinator]


@dataclass
class ScheduledStart:
    """A pending scheduled start for a kiln."""

    kiln_id: str
    sched_num: int
    start_at: datetime
    armed: bool = True


@dataclass
class PolygonKilnsData:
    """Data fetched on each coordinator cycle."""

    kilns: dict[str, dict[str, Any]] = field(default_factory=dict)
    schedules: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    last_firing: dict[str, dict[str, Any]] = field(default_factory=dict)


class PolygonKilnsCoordinator(DataUpdateCoordinator[PolygonKilnsData]):
    """Poll the Firebase backend and trigger scheduled starts."""

    config_entry: PolygonConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: PolygonConfigEntry,
        client: PolygonKilnsClient,
    ) -> None:
        """Initialize the coordinator."""
        interval = config_entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self.scheduled_starts: dict[str, ScheduledStart] = {}
        self.selected_programs: dict[str, int] = {}
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{config_entry.entry_id}")

    async def async_setup(self) -> None:
        """Restore persisted scheduled starts and program selections."""
        stored = await self._store.async_load()
        if not stored:
            return
        for kiln_id, raw in stored.get("scheduled_starts", {}).items():
            start_at = dt_util.parse_datetime(raw["start_at"])
            if start_at is None:
                continue
            self.scheduled_starts[kiln_id] = ScheduledStart(
                kiln_id=kiln_id,
                sched_num=raw["sched_num"],
                start_at=start_at,
                armed=raw.get("armed", True),
            )
        for kiln_id, sched_num in stored.get("selected_programs", {}).items():
            self.selected_programs[kiln_id] = sched_num

    async def _async_persist_state(self) -> None:
        """Persist scheduled starts and selections so they survive restarts."""
        await self._store.async_save(
            {
                "scheduled_starts": {
                    kiln_id: {
                        "sched_num": start.sched_num,
                        "start_at": start.start_at.isoformat(),
                        "armed": start.armed,
                    }
                    for kiln_id, start in self.scheduled_starts.items()
                },
                "selected_programs": dict(self.selected_programs),
            }
        )

    async def async_select_program(self, kiln_id: str, sched_num: int) -> None:
        """Remember and persist the program selected for a kiln."""
        self.selected_programs[kiln_id] = sched_num
        await self._async_persist_state()

    async def async_set_scheduled_start(
        self, kiln_id: str, sched_num: int, start_at: datetime, armed: bool
    ) -> None:
        """Create or update the scheduled start for a kiln."""
        self.scheduled_starts[kiln_id] = ScheduledStart(
            kiln_id=kiln_id, sched_num=sched_num, start_at=start_at, armed=armed
        )
        await self._async_persist_state()
        self.async_update_listeners()

    async def async_set_scheduled_start_armed(self, kiln_id: str, armed: bool) -> None:
        """Arm or disarm the scheduled start for a kiln."""
        if start := self.scheduled_starts.get(kiln_id):
            start.armed = armed
            await self._async_persist_state()
            self.async_update_listeners()

    async def _async_update_data(self) -> PolygonKilnsData:
        """Fetch kiln, schedule and firing data, and fire scheduled starts."""
        try:
            kilns = {k["_id"]: k for k in await self.client.async_get_kilns()}
            schedules_list = await asyncio.gather(
                *(self.client.async_get_schedules(kiln_id) for kiln_id in kilns)
            )
            firings_list = await asyncio.gather(
                *(self.client.async_get_firings(kiln_id, limit=1) for kiln_id in kilns)
            )
        except PolygonAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (PolygonConnectionError, PolygonKilnsApiError) as err:
            raise UpdateFailed(str(err)) from err

        data = PolygonKilnsData(
            kilns=kilns,
            schedules={
                kiln_id: sorted(s, key=lambda s: s.get("schedNum", 0))
                for kiln_id, s in zip(kilns, schedules_list, strict=True)
            },
            last_firing={
                kiln_id: f[0]
                for kiln_id, f in zip(kilns, firings_list, strict=True)
                if f
            },
        )

        await self._async_check_scheduled_starts(data)
        self._async_maybe_save_refresh_token()
        return data

    async def _async_check_scheduled_starts(self, data: PolygonKilnsData) -> None:
        """Trigger armed scheduled starts whose time has come."""
        now = dt_util.utcnow()
        changed = False
        for kiln_id, start in list(self.scheduled_starts.items()):
            if not start.armed or start.start_at > now:
                continue
            kiln = data.kilns.get(kiln_id)
            kiln_name = (kiln or {}).get("name", kiln_id)
            error: str | None = None
            if kiln is None or not self.kiln_is_online(kiln):
                error = "el horno no está en línea"
            elif str(kiln.get("state", "")).lower() not in STARTABLE_STATES:
                error = f"el horno está en estado '{kiln.get('state')}'"

            if error is None:
                try:
                    await self.client.async_request_start(kiln_id, start.sched_num)
                    _LOGGER.info(
                        "Inicio programado disparado: horno %s, programa %s",
                        kiln_id,
                        start.sched_num,
                    )
                except PolygonKilnsApiError as err:
                    error = str(err)

            if error is not None:
                _LOGGER.warning(
                    "No se pudo ejecutar el inicio programado del horno %s: %s",
                    kiln_id,
                    error,
                )
                self.hass.components.persistent_notification.async_create(
                    f"No se pudo iniciar el programa {start.sched_num} en "
                    f"'{kiln_name}': {error}.",
                    title="Polygon Kilns: inicio programado fallido",
                    notification_id=f"{DOMAIN}_scheduled_start_{kiln_id}",
                )

            del self.scheduled_starts[kiln_id]
            changed = True

        if changed:
            await self._async_persist_state()

    def _async_maybe_save_refresh_token(self) -> None:
        """Persist the refresh token if Firebase rotated it."""
        current = self.client.refresh_token
        if current and current != self.config_entry.data.get(CONF_REFRESH_TOKEN):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_REFRESH_TOKEN: current},
            )

    @staticmethod
    def kiln_is_online(kiln: dict[str, Any]) -> bool:
        """Return True if the kiln reported in recently."""
        last_seen = kiln.get("lastSeen")
        if not last_seen:
            return False
        parsed = dt_util.parse_datetime(str(last_seen))
        if parsed is None:
            return False
        return dt_util.utcnow() - parsed < OFFLINE_AFTER
